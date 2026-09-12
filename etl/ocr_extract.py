"""從 46 份非營利財報抽出附表二（經費流用及勻支檢查表）的人事費細項。"""
import pdfplumber, re, glob, os, json, collections

OCR = r'I:\黑客松\2026新北生成式AI黑客松\aws-hackathon\data\ocr'
NUM = r'\$?\s*\(?([\d,]+)\)?'

# OCR 錯字對照：財報常見的辨識錯誤
ALIAS = {
    '人事責':'人事費','人事賡':'人事費','人事費':'人事費',
    '加班費':'加班費','加班責':'加班費','加班賡':'加班費',
    '代課費及代班費':'代課代班費','代課代班費':'代課代班費','代課費':'代課代班費',
    '園長及教保服務人員薪資':'教保薪資','圍長及教保服務人員薪資':'教保薪資',
    '園長及教保人員薪資':'教保薪資','教保服務人員薪資':'教保薪資',
    '勞退金提撥':'勞退提撥','勞退提撥':'勞退提撥',
    '資遣費':'資遣費','資遺費':'資遣費',
}

def parse_money(s):
    s = s.replace(',', '').replace('$','').strip()
    neg = s.startswith('(') or s.endswith(')')
    s = s.strip('()')
    if not s.isdigit(): return None
    return -int(s) if neg else int(s)

def extract(path):
    out = {}
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            t = pg.extract_text() or ''
            if '流用' not in t and '勻支' not in t and '預決算檢查' not in t:
                continue
            for line in t.split('\n'):
                m = re.match(r'^\s*([\u4e00-\u9fff（）\(\)A-Za-z、 ]{2,20}?)\s+' + NUM + r'\s+' + NUM, line)
                if not m: continue
                raw, b, d = m.group(1).strip(), parse_money(m.group(2)), parse_money(m.group(3))
                key = ALIAS.get(raw.replace(' ',''))
                if key and b and b > 0 and d is not None:
                    if key not in out:          # 同名取第一次（合計列在前）
                        out[key] = {'budget': b, 'actual': d, 'rate': round(d/b, 4)}
    return out

rows = []
for p in sorted(glob.glob(os.path.join(OCR, '*.pdf'))):
    code, yr = re.match(r'(N\d+[^_]+)_(\d+)\.pdf', os.path.basename(p)).groups()
    d = extract(p)
    rows.append({'park': code, 'year': int(yr), 'items': d})
    print(f"{code:8s} {yr}  " + "  ".join(f"{k}={v['rate']:.0%}" for k,v in sorted(d.items())) or "(無)")

json.dump(rows, open('fin_extract.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
print()
found = collections.Counter()
for r in rows:
    for k in r['items']: found[k] += 1
print("各欄位在 46 份中出現次數:", dict(found))
per = [(r['park'], r['year'], r['items']['人事費']['rate']) for r in rows if '人事費' in r['items']]
per.sort(key=lambda x: x[2])
print(f"\n人事費執行率 n={len(per)}")
import statistics
print(f"  中位數 {statistics.median(x[2] for x in per):.0%}  平均 {statistics.mean(x[2] for x in per):.0%}")
print("  最低 5 筆:", [(p,y,f'{r:.0%}') for p,y,r in per[:5]])
print("  N09 安興:", [(y,f'{r:.0%}') for p,y,r in per if p.startswith('N09')])
