"""建立法規知識庫（Bedrock Knowledge Base + S3 Vectors），逐份匯入條文。ADR-0005。

    python -m etl.laws                                   # 先產生 out/kb/laws.jsonl
    AWS_PROFILE=hackathon python infra/rag/setup_kb.py            # 建資源 + 匯入（可中斷續跑）
    AWS_PROFILE=hackathon python infra/rag/setup_kb.py --query 師生比  # 單題檢索
    AWS_PROFILE=hackathon python infra/rag/setup_kb.py --eval         # 15 題檢索命中率

## 為什麼不用 StartIngestionJob

競賽規範：Bedrock 請求 ≤ 每秒 1 次。批次匯入時 Bedrock 自己決定嵌入速度，
我們管不到。這裡改用 custom data source + IngestKnowledgeBaseDocuments：
一次只送一份（etl/laws.py 已切成一條條文一份、chunking = NONE），輪詢到
INDEXED 才送下一份。**所有 Bedrock 呼叫（含輪詢）都經過同一個 Pacer**，
任意 1 秒內最多 1 個請求。匯入期間不要同時 Demo 對答功能。
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
REGION = "us-west-2"
NAME = "watchdog-laws"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
DIMENSION = 1024
DOCS = ROOT / "out" / "kb" / "laws.jsonl"
DONE = ROOT / "out" / "kb" / "ingested.txt"


class Pacer:
    """相鄰兩個 Bedrock 請求至少間隔 interval 秒。"""

    def __init__(self, interval=1.1):
        self.interval = interval
        self.last = 0.0

    def __call__(self, fn, **kwargs):
        wait = self.last + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return fn(**kwargs)
        finally:
            self.last = time.monotonic()


pace = Pacer()


def clients():
    session = boto3.Session(region_name=REGION)
    return {name: session.client(name) for name in
            ("sts", "iam", "s3vectors", "bedrock-agent", "bedrock-agent-runtime")}


def ensure_vectors(c, account):
    bucket = f"watchdog-kb-{account}"
    try:
        c["s3vectors"].get_vector_bucket(vectorBucketName=bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] != "NotFoundException":
            raise
        c["s3vectors"].create_vector_bucket(vectorBucketName=bucket)
        print(f"建立 vector bucket {bucket}")
    try:
        index = c["s3vectors"].get_index(vectorBucketName=bucket, indexName=NAME)["index"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "NotFoundException":
            raise
        c["s3vectors"].create_index(
            vectorBucketName=bucket, indexName=NAME, dataType="float32",
            dimension=DIMENSION, distanceMetric="cosine",
            # 條文全文與 KB 內部 metadata 超過可篩選欄位的 2KB 上限，必須標為不可篩選。
            metadataConfiguration={"nonFilterableMetadataKeys":
                                   ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]},
        )
        index = c["s3vectors"].get_index(vectorBucketName=bucket, indexName=NAME)["index"]
        print(f"建立 vector index {NAME}")
    return index["indexArn"]


def ensure_role(c, account, index_arn):
    role = f"{NAME}-kb-role"
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": account}},
        }],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": "bedrock:InvokeModel",
             "Resource": f"arn:aws:bedrock:{REGION}::foundation-model/{EMBED_MODEL}"},
            {"Effect": "Allow",
             "Action": ["s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
                        "s3vectors:QueryVectors", "s3vectors:GetIndex"],
             "Resource": index_arn},
        ],
    }
    created = False
    try:
        arn = c["iam"].get_role(RoleName=role)["Role"]["Arn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        arn = c["iam"].create_role(RoleName=role, AssumeRolePolicyDocument=json.dumps(trust))["Role"]["Arn"]
        created = True
        print(f"建立 IAM role {role}")
    c["iam"].put_role_policy(RoleName=role, PolicyName="kb-access", PolicyDocument=json.dumps(policy))
    if created:
        time.sleep(15)        # IAM 最終一致；剛建的 role 立刻給 Bedrock 用會被拒
    return arn


def ensure_kb(c, role_arn, index_arn):
    agent = c["bedrock-agent"]
    found = [kb for kb in pace(agent.list_knowledge_bases)["knowledgeBaseSummaries"] if kb["name"] == NAME]
    if found:
        kb_id = found[0]["knowledgeBaseId"]
    else:
        kb_id = pace(
            agent.create_knowledge_base,
            name=NAME, roleArn=role_arn,
            description="新北幼兒園稽查相關法規，一條條文一份文件",
            knowledgeBaseConfiguration={
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": f"arn:aws:bedrock:{REGION}::foundation-model/{EMBED_MODEL}",
                    "embeddingModelConfiguration": {"bedrockEmbeddingModelConfiguration": {
                        "dimensions": DIMENSION, "embeddingDataType": "FLOAT32"}},
                },
            },
            storageConfiguration={"type": "S3_VECTORS", "s3VectorsConfiguration": {"indexArn": index_arn}},
        )["knowledgeBase"]["knowledgeBaseId"]
        print(f"建立 knowledge base {kb_id}")
    while (status := pace(agent.get_knowledge_base, knowledgeBaseId=kb_id)["knowledgeBase"]["status"]) != "ACTIVE":
        if status == "FAILED":
            raise RuntimeError("knowledge base 建立失敗")
        time.sleep(3)

    sources = pace(agent.list_data_sources, knowledgeBaseId=kb_id)["dataSourceSummaries"]
    found = [s for s in sources if s["name"] == NAME]
    if found:
        ds_id = found[0]["dataSourceId"]
    else:
        ds_id = pace(
            agent.create_data_source,
            knowledgeBaseId=kb_id, name=NAME,
            dataSourceConfiguration={"type": "CUSTOM"},
            vectorIngestionConfiguration={"chunkingConfiguration": {"chunkingStrategy": "NONE"}},
        )["dataSource"]["dataSourceId"]
        print(f"建立 data source {ds_id}")
    return kb_id, ds_id


def document(doc):
    attributes = [{"key": k, "value": {"type": "STRING", "stringValue": v}}
                  for k, v in doc["metadata"].items() if v]
    return {
        "metadata": {"type": "IN_LINE_ATTRIBUTE", "inlineAttributes": attributes},
        "content": {
            "dataSourceType": "CUSTOM",
            "custom": {
                "customDocumentIdentifier": {"id": doc["id"]},
                "sourceType": "IN_LINE",
                "inlineContent": {"type": "TEXT", "textContent": {"data": doc["text"]}},
            },
        },
    }


def text_hash(doc):
    return hashlib.sha1(doc["text"].encode()).hexdigest()[:12]


def ingest(c, kb_id, ds_id):
    agent = c["bedrock-agent"]
    docs = [json.loads(line) for line in DOCS.read_text(encoding="utf-8").splitlines()]
    # ingested.txt 每行「id 內文雜湊」。etl/laws.py 改了切段或清洗規則時，
    # 內文變了的文件會重送（同 id 覆寫），沒變的跳過。舊格式只有 id 的行視為未變。
    done = {}
    if DONE.exists():
        for line in DONE.read_text().splitlines():
            ident, _, digest = line.partition(" ")
            done[ident] = digest
    todo = [d for d in docs
            if d["id"] not in done or (done[d["id"]] and done[d["id"]] != text_hash(d))]
    print(f"共 {len(docs)} 份，已完成 {len(done)}，待匯入 {len(todo)}"
          f"（約 {len(todo) * 3 // 60} 分鐘）")
    failed = []
    with open(DONE, "a") as log:
        for n, doc in enumerate(todo, 1):
            pace(agent.ingest_knowledge_base_documents,
                 knowledgeBaseId=kb_id, dataSourceId=ds_id, documents=[document(doc)])
            ident = [{"dataSourceType": "CUSTOM", "custom": {"id": doc["id"]}}]
            while True:
                detail = pace(agent.get_knowledge_base_documents, knowledgeBaseId=kb_id,
                              dataSourceId=ds_id, documentIdentifiers=ident)["documentDetails"][0]
                if detail["status"] in ("INDEXED", "FAILED", "METADATA_UPDATE_FAILED"):
                    break
            if detail["status"] == "INDEXED":
                log.write(f"{doc['id']} {text_hash(doc)}\n")
                log.flush()
            else:
                failed.append((doc["id"], detail.get("statusReason", "")))
            if n % 20 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  失敗 {len(failed)}")
    for ident, reason in failed:
        print(f"失敗 {ident}: {reason}")


def retrieve(c, kb_id, text, k=5):
    return pace(c["bedrock-agent-runtime"].retrieve, knowledgeBaseId=kb_id, retrievalQuery={"text": text},
                retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": k}})["retrievalResults"]


# 稽查員會問的題目 → 預期要檢索到的法規。命中 = top-5 裡出現該法規。
EVAL = [
    ("班級人數與師生比的上限", "幼兒教育及照顧法"),
    ("幼兒園超收幼兒人數會被怎麼罰", "新北市政府處理違反幼兒教育及照顧法與教保服務人員條例事件裁罰基準"),
    ("幼童專用車的隨車人員規定", "幼兒園幼童專用車輛與其駕駛人及隨車人員督導管理辦法"),
    ("教保服務人員體罰或不當對待幼兒", "教保服務人員條例"),
    ("不當管教的定義與處理", "教保服務人員輔導與管教幼兒注意事項"),
    ("家長中途退學的退費比例", "新北市教保服務機構收退費辦法"),
    ("幼兒園可以收哪些費用", "教保服務機構收費項目及用途"),
    ("餐點營養與食物內容的標準", "幼兒園餐點食物內容及營養基準"),
    ("室內活動室每人面積最低標準", "幼兒園及其分班基本設施設備標準"),
    ("進用未具資格的教保員", "教保服務人員條例"),
    ("腸病毒停課標準", "新北市公私立學校及幼兒園腸病毒通報及停課作業規定"),
    ("評鑑項目與追蹤評鑑", "幼兒園評鑑辦法"),
    ("兼辦國小課後照顧需要核准嗎", "幼兒園兼辦國民小學兒童課後照顧服務辦法"),
    ("幼兒園負責人違法時會公布姓名多久", "幼兒教育及照顧法與教保服務人員條例公布負責人行為人機構名稱及場址之公布期間"),
    ("未辦理幼兒團體保險的罰鍰", "新北市政府處理違反幼兒教育及照顧法與教保服務人員條例事件裁罰基準"),
]


def law_of(result):
    return result.get("metadata", {}).get("law_name", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query")
    ap.add_argument("--eval", action="store_true")
    args = ap.parse_args()

    c = clients()
    account = c["sts"].get_caller_identity()["Account"]
    index_arn = ensure_vectors(c, account)
    role_arn = ensure_role(c, account, index_arn)
    kb_id, ds_id = ensure_kb(c, role_arn, index_arn)
    print(f"KB_ID={kb_id}  DATA_SOURCE_ID={ds_id}")

    if args.query:
        for r in retrieve(c, kb_id, args.query):
            print(f"{r['score']:.3f}  {law_of(r)} {r['metadata'].get('article', '')}")
        return
    if args.eval:
        hits = 0
        for question, expected in EVAL:
            laws = [law_of(r) for r in retrieve(c, kb_id, question)]
            hit = expected in laws
            hits += hit
            print(f"{'✅' if hit else '❌'} {question} → {laws[:3]}")
        print(f"\ntop-5 命中 {hits}/{len(EVAL)} = {hits / len(EVAL):.0%}（門檻 80%）")
        return
    ingest(c, kb_id, ds_id)


if __name__ == "__main__":
    main()
