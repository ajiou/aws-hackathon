"""把 sentinel 的輿情資料匯出成可進版控的 JSON。

剝掉三類不該進 repo 的內容：
  1. 自然人姓名 —— parks.owner、punishments.target、park_aliases 的 owner 別名
  2. 新聞全文 docs.body —— 1.6M 字元，有著作權疑慮，且 SRI 不需要
     （LLM 已把它蒸餾進 doc_analysis）
  3. parks / punishments 兩張表整個不匯出 —— repo 裡已有等價資料
     （preschools.json、園所裁罰特徵_cutoff20250101.json）

用法: python export_media.py <watchdog.db> <輸出目錄>
"""
import json
import os
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else r'sentinel\data\watchdog.db'
OUT = sys.argv[2] if len(sys.argv) > 2 else r'aws-hackathon\data\media'

# 表 -> (SELECT 子句, 排序, 說明)
EXPORTS = {
    'docs': (
        "SELECT doc_id, source, outlet, source_url, published_at, title, query, "
        "fetched_at, body_status, push_count, push_score FROM docs ORDER BY doc_id",
        '原始文件。刻意不含 body（新聞全文），SRI 只用得到標題與來源。'),
    'doc_resolution': (
        "SELECT doc_id, level, town, park_type, candidate_count, reason "
        "FROM doc_resolution ORDER BY doc_id",
        '實體解析結果。level A 明文點名 / B 只到行政區 / C 只到全市 / X 非新北或非教保。'),
    'doc_links': (
        # matched_alias 在 alias_kind='owner' 時存的是自然人姓名，一律遮蔽。
        "SELECT doc_id, park_id, confidence, "
        "CASE WHEN alias_kind = 'owner' THEN NULL ELSE matched_alias END AS matched_alias, "
        "alias_kind FROM doc_links ORDER BY doc_id, park_id",
        'A 級文件綁定到園所。park_id 與 preschools.json 的 id 相同。'
        'alias_kind=owner 的 matched_alias 已遮蔽為 null（那是自然人姓名）。'),
    'doc_analysis': (
        "SELECT doc_id, event_type, severity, stance, credibility, "
        "targets_institution, is_ad, reason, model, analyzed_at "
        "FROM doc_analysis ORDER BY doc_id",
        'LLM 抽取結果。只標了 580/2900，其餘待補（SPEC §5.5）。'),
    'park_aliases': (
        "SELECT alias, park_id, kind, ambiguous, is_place FROM park_aliases "
        "WHERE kind != 'owner' ORDER BY park_id, alias",
        "園所別名字典。已排除 kind='owner' 的列（那是自然人姓名）。"),
    'park_risk': (
        "SELECT as_of, park_id, sri, compliance, event_count, doc_count, "
        "last_event_date, top_event_type, top_severity, is_burst "
        "FROM park_risk ORDER BY park_id",
        '既有 SRI 計算結果，供對照用。正式分數由 model/score.py 重算。'),
    'district_heat': (
        "SELECT as_of, town, heat, doc_count, candidate_pool, heat_per_park "
        "FROM district_heat ORDER BY town",
        '行政區輿情熱度，SPEC §5.5 的 L2 層。'),
}

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
os.makedirs(OUT, exist_ok=True)

manifest = []
for table, (sql, note) in EXPORTS.items():
    rows = [dict(r) for r in conn.execute(sql)]
    path = os.path.join(OUT, table + '.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    size = os.path.getsize(path)
    manifest.append((table, len(rows), size, note))
    print('  %-16s %6d 列  %9s  %s' % (table, len(rows), '{:,}'.format(size), path))

# 個資回頭檢查：匯出的檔案裡不得出現 parks.owner 的任何一個姓名
owners = {r[0].strip() for r in conn.execute(
    "SELECT owner FROM parks WHERE owner IS NOT NULL AND owner != ''")}
owners = {o for o in owners if 2 <= len(o) <= 4}
hits = []
for table, _, _, _ in manifest:
    text = open(os.path.join(OUT, table + '.json'), encoding='utf-8').read()
    for o in owners:
        if '"' + o + '"' in text or '：' + o in text:
            hits.append((table, o))
print()
if hits:
    print('個資殘留 %d 處：%s' % (len(hits), hits[:10]))
    sys.exit(1)
print('個資檢查通過：%d 個負責人姓名皆未出現在匯出檔中' % len(owners))
conn.close()

with open(os.path.join(OUT, '_manifest.json'), 'w', encoding='utf-8') as fh:
    json.dump([{'table': t, 'rows': n, 'bytes': s, 'note': d}
               for t, n, s, d in manifest], fh, ensure_ascii=False, indent=1)
