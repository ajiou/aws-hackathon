# 輿情資料

`sentinel/data/watchdog.db` 的匯出。原始 SQLite **不進版控**，理由見下方「拿掉了什麼」。

對應 [`../../docs/SPEC.md`](../../docs/SPEC.md) §5.5 輿情維度三層設計。

---

## 檔案

| 檔案 | 列數 | 內容 |
|---|---:|---|
| `docs.json` | 2,900 | 原始文件。**不含 `body`**（新聞全文），SRI 只用得到標題與來源 |
| `doc_resolution.json` | 2,900 | 實體解析結果。`level` = A 明文點名 / B 只到行政區 / C 只到全市 / X 非新北或非教保 |
| `doc_links.json` | 209 | A 級文件綁定到園所。`park_id` 與 `preschools.json` 的 `id` 相同 |
| `doc_analysis.json` | 580 | LLM 抽取結果（`event_type` / `severity` / `credibility` / `stance` / `is_ad` / `targets_institution`） |
| `park_aliases.json` | 5,068 | 園所別名字典 |
| `park_risk.json` | 491 | 既有 SRI 計算結果，供對照 |
| `district_heat.json` | 14 | 行政區熱度，SPEC §5.5 的 L2 層 |

`_manifest.json` 記錄每份檔案的列數、大小與說明。

---

## 三層覆蓋率（這是最重要的一件事）

| 層級 | 來源 | 覆蓋 |
|---|---|---|
| **L1 園級** | `doc_links`（A 級） | **40 園 / 1,178 = 3.3%** |
| **L2 區級** | `doc_resolution` level=B 聚到 `town` | **29 區 = 100% 園所** |
| L3 市級 | level=C | 只作趨勢，不進分數 |

`doc_resolution.level` 的分布：A 161 / B 352 / C 137 / X 2,250。

**只用 L1 的話，96.7% 的園所輿情 `coverage = 0`，該維度的權重形同虛設。**
必須加上 L2 才有意義。SPEC §5.5 的維度內權重是 L1 60% / L2 40%。

---

## ⚠ 待補：`doc_analysis` 只標了 580 / 2,900

其餘 2,320 篇尚未經 LLM 抽取，因此 `doc_links` 裡有一部分文件算不進 SRI。

補標方式見 SPEC §5.5，用 Bedrock，**1 RPS 限制下約 39 分鐘**，離線批次跑。
這項列在 [`../../docs/ASSIGNMENTS.md`](../../docs/ASSIGNMENTS.md) 的不可砍清單。

---

## 拿掉了什麼，為什麼

匯出時剝掉三類內容。`etl/export_media.py` 每次執行都會回頭掃一次，
確認 `parks.owner` 的 948 個姓名沒有任何一個出現在輸出檔中，有殘留就 exit 1。

| 拿掉的 | 原因 |
|---|---|
| `parks` 與 `punishments` 兩張表 | repo 內已有等價資料：`preschools.json`、`園所裁罰特徵_cutoff20250101.json`。`park_id` 是同一組 UUID，直接 join |
| `parks.owner`、`punishments.target` | 自然人姓名 |
| `park_aliases` 中 `kind='owner'` 的列 | 同上，那些別名就是負責人姓名 |
| `doc_links.matched_alias` 當 `alias_kind='owner'` | 同上。已遮蔽為 `null`，`alias_kind` 保留供判斷 |
| `docs.body` | 1,622,657 字元的新聞全文。有著作權疑慮，且 SRI 用不到——LLM 已把它蒸餾進 `doc_analysis` |

> 這比競賽規範第 2 條要求的更嚴：規範管的是「上傳到 AWS 帳戶」，而
> 這裡是 GitHub。但姓名一旦進版控就很難拔乾淨（要改寫歷史），
> 所以在源頭就不要放進去。

---

## 怎麼用

`park_id` 是全系統共用的主鍵，與 `data/preschools.json` 的 `id` 完全相同。

```python
import json, collections

docs  = {d['doc_id']: d for d in json.load(open('data/media/docs.json', encoding='utf-8'))}
links = json.load(open('data/media/doc_links.json', encoding='utf-8'))
anal  = {a['doc_id']: a for a in json.load(open('data/media/doc_analysis.json', encoding='utf-8'))}
res   = {r['doc_id']: r for r in json.load(open('data/media/doc_resolution.json', encoding='utf-8'))}

# L1：某園的 A 級負面文件（已排除廣告與非指向機構者）
by_park = collections.defaultdict(list)
for l in links:
    a = anal.get(l['doc_id'])
    if a and not a['is_ad'] and a['targets_institution']:
        by_park[l['park_id']].append((docs[l['doc_id']], a, l['confidence']))

# L2：區級熱度的原始素材
b_level = [r for r in res.values() if r['level'] == 'B' and r['town']]
```

SRI 的完整公式（去重、共振、半衰期）見 SPEC §5.5。

---

## 重新匯出

資料庫更新後：

```bash
python etl/export_media.py <watchdog.db 路徑> data/media
```

沒帶參數時預設 `sentinel/data/watchdog.db` → `aws-hackathon/data/media`。
