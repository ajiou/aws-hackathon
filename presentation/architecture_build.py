"""產生 presentation 字級的架構圖 SVG 區塊。

字級：節點名 16 / 子標 12 / 箭頭標 11 / 型別標 9 / 邊註 20 / 圖例 12
幾何：viewBox 1440x848，所有座標為 4 的倍數
"""
import io

ICONS = """    <g id="ic-db" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 6a8 3 0 1 0 16 0a8 3 0 1 0 -16 0"/><path d="M4 6v6a8 3 0 0 0 16 0v-6"/><path d="M4 12v6a8 3 0 0 0 16 0v-6"/>
    </g>
    <g id="ic-lock" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M5 13a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v6a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2v-6"/><path d="M11 16a1 1 0 1 0 2 0a1 1 0 0 0 -2 0"/><path d="M8 11v-4a4 4 0 1 1 8 0v4"/>
    </g>
    <g id="ic-robot" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M6 6a2 2 0 0 1 2 -2h8a2 2 0 0 1 2 2v4a2 2 0 0 1 -2 2h-8a2 2 0 0 1 -2 -2l0 -4"/><path d="M12 2v2"/><path d="M9 12v9"/><path d="M15 12v9"/><path d="M5 16l4 -2"/><path d="M15 14l4 2"/><path d="M9 18h6"/><path d="M10 8v.01"/><path d="M14 8v.01"/>
    </g>
    <g id="ic-bucket" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 7a8 4 0 1 0 16 0a8 4 0 1 0 -16 0"/><path d="M4 7c0 .664 .088 1.324 .263 1.965l2.737 10.035c.5 1.5 2.239 2 5 2s4.5 -.5 5 -2c.333 -1 1.246 -4.345 2.737 -10.035a7.45 7.45 0 0 0 .263 -1.965"/>
    </g>
    <g id="ic-users" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M5 7a4 4 0 1 0 8 0a4 4 0 1 0 -8 0"/><path d="M3 21v-2a4 4 0 0 1 4 -4h4a4 4 0 0 1 4 4v2"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/><path d="M21 21v-2a4 4 0 0 0 -3 -3.85"/>
    </g>
    <g id="ic-cdn" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M19.5 7a9 9 0 0 0 -7.5 -4a8.991 8.991 0 0 0 -7.484 4"/><path d="M11.5 3a16.989 16.989 0 0 0 -1.826 4"/><path d="M12.5 3a16.989 16.989 0 0 1 1.828 4"/><path d="M19.5 17a9 9 0 0 1 -7.5 4a8.991 8.991 0 0 1 -7.484 -4"/><path d="M11.5 21a16.989 16.989 0 0 1 -1.826 -4"/><path d="M12.5 21a16.989 16.989 0 0 0 1.828 -4"/><path d="M2 10l1 4l1.5 -4l1.5 4l1 -4"/><path d="M17 10l1 4l1.5 -4l1.5 4l1 -4"/>
    </g>
    <g id="ic-api" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M7 4a2 2 0 0 0 -2 2v3a2 3 0 0 1 -2 3a2 3 0 0 1 2 3v3a2 2 0 0 0 2 2"/><path d="M17 4a2 2 0 0 1 2 2v3a2 3 0 0 0 2 3a2 3 0 0 0 -2 3v3a2 2 0 0 1 -2 2"/>
    </g>"""

SANS = "'Geist','Noto Sans TC',sans-serif"
MONO = "'Geist Mono', monospace"
SERIF = "'Instrument Serif', serif"
P = []


def a(line):
    P.append(line)


def node(x, y, w, h, fill, stroke, sw, tag, tagw, tagcol, icon, iccol,
         name, sub, extra=None, extra2=None):
    cy = y + h // 2
    a('  <rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="#f5f5f5"/>' % (x, y, w, h))
    a('  <rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="%s" stroke="%s" stroke-width="%s"/>'
      % (x, y, w, h, fill, stroke, sw))
    a('  <g transform="translate(%d,%d) scale(1.7)" color="%s"><use href="#%s"/></g>'
      % (x + 24, cy - 20, iccol, icon))
    a('  <rect x="%d" y="%d" width="%d" height="16" rx="3" fill="transparent" stroke="%s" stroke-width="1"/>'
      % (x + w - tagw - 16, y + 16, tagw, tagcol))
    a('  <text x="%d" y="%d" fill="%s" font-size="9" font-family="%s" text-anchor="middle" letter-spacing="0.08em">%s</text>'
      % (x + w - tagw // 2 - 16, y + 28, tagcol, MONO, tag))
    tx = x + 80
    base = cy - 12 if extra2 else (cy - 8 if extra else cy - 2)
    a('  <text x="%d" y="%d" fill="#2d3142" font-size="16" font-weight="600" font-family="%s">%s</text>'
      % (tx, base, SANS, name))
    a('  <text x="%d" y="%d" fill="#4f5d75" font-size="12" font-family="%s">%s</text>'
      % (tx, base + 24, MONO, sub))
    if extra:
        a('  <text x="%d" y="%d" fill="#7a8399" font-size="12" font-family="%s">%s</text>'
          % (x + 24, base + 48, SANS, extra))
    if extra2:
        a('  <text x="%d" y="%d" fill="#7a8399" font-size="12" font-family="%s">%s</text>'
          % (x + 24, base + 70, MONO, extra2))


def alabel(cx, y, w, txt, col="#7a8399"):
    a('  <rect x="%d" y="%d" width="%d" height="16" rx="3" fill="#f5f5f5"/>' % (cx - w // 2, y, w))
    a('  <text x="%d" y="%d" fill="%s" font-size="11" font-family="%s" text-anchor="middle" letter-spacing="0.06em">%s</text>'
      % (cx, y + 12, col, MONO, txt))


def zone(x, y, w, h, lx, lw, txt):
    a('  <rect x="%d" y="%d" width="%d" height="%d" rx="12" fill="rgba(45,49,66,0.02)" stroke="rgba(45,49,66,0.10)" stroke-width="1"/>'
      % (x, y, w, h))
    a('  <rect x="%d" y="%d" width="%d" height="16" rx="3" fill="#f5f5f5"/>' % (lx, y + 4, lw))
    a('  <text x="%d" y="%d" fill="rgba(45,49,66,0.40)" font-size="9" font-family="%s" text-anchor="middle" letter-spacing="0.14em">%s</text>'
      % (lx + lw // 2, y + 16, MONO, txt))


a('<svg class="diagram" viewBox="0 0 1440 848" role="img" aria-labelledby="arch-title arch-desc" xmlns="http://www.w3.org/2000/svg">')
a('  <title id="arch-title">小小守護員系統架構</title>')
a('  <desc id="arch-desc">上方為每日一次的離線批次層：六個公開資料源經過 ETL 與個資雜湊，交由 Bedrock 與 SageMaker 運算，結果寫入 S3 資料層。下方為線上服務層：稽查員經 CloudFront 取得前端與 API，Lambda 只讀取 S3 上算好的靜態分數，不做線上推論。</desc>')
a('')
a('  <defs>')
for mid, col in [("arrow", "#4f5d75"), ("arrow-accent", "#eb6c36"), ("arrow-link", "#2e5aa8")]:
    a('    <marker id="%s" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">' % mid)
    a('      <polygon points="0 0, 8 3, 0 6" fill="%s"/>' % col)
    a('    </marker>')
a(ICONS)
a('  </defs>')
a('')
a('  <rect width="100%" height="100%" fill="#f5f5f5"/>')
a('')
a('  <!-- ZONES -->')
zone(48, 120, 1344, 216, 76, 292, "OFFLINE BATCH · ONCE A DAY")
zone(48, 448, 1344, 232, 76, 316, "ONLINE SERVING · READ-ONLY")
a('')
a('  <!-- ARROWS -->')
a('  <line x1="344" y1="228" x2="400" y2="228" stroke="#4f5d75" stroke-width="1.4" marker-end="url(#arrow)"/>')
a('  <line x1="704" y1="228" x2="760" y2="228" stroke="#eb6c36" stroke-width="1.4" marker-end="url(#arrow-accent)"/>')
alabel(732, 196, 48, "HASHED", "#eb6c36")
a('  <line x1="1064" y1="228" x2="1120" y2="228" stroke="#4f5d75" stroke-width="1.4" marker-end="url(#arrow)"/>')
alabel(1092, 196, 48, "WRITE")
a('  <line x1="344" y1="560" x2="400" y2="560" stroke="#2e5aa8" stroke-width="1.4" marker-end="url(#arrow-link)"/>')
alabel(372, 528, 48, "HTTPS")
a('  <path d="M 704 536 H 724 Q 732 536 732 528 V 520 Q 732 512 740 512 H 760" fill="none" stroke="#4f5d75" stroke-width="1.4" marker-end="url(#arrow)"/>')
alabel(732, 472, 48, "OAC")
a('  <path d="M 704 584 H 724 Q 732 584 732 592 V 604 Q 732 612 740 612 H 760" fill="none" stroke="#2e5aa8" stroke-width="1.4" marker-end="url(#arrow-link)"/>')
alabel(700, 628, 56, "/API/*")
a('  <path d="M 1104 612 H 1240 Q 1248 612 1248 604 V 340" fill="none" stroke="#4f5d75" stroke-width="1.4" marker-end="url(#arrow)"/>')
alabel(1320, 416, 120, "READ SERVING/")
a('')
a('  <!-- NODES -->')
node(88, 164, 256, 128, "rgba(79,93,117,0.10)", "#7a8399", 1.2, "INPUT", 44,
     "rgba(122,131,153,0.9)", "ic-db", "#4f5d75", "六個公開資料源", "1,178 parks",
     "基本 · 評鑑 · 裁罰 · 收費 · 財報 · 輿情")
node(400, 164, 304, 128, "rgba(235,108,54,0.08)", "#eb6c36", 1.6, "ETL", 36,
     "rgba(235,108,54,0.95)", "ic-lock", "#eb6c36", "清洗 · 特徵 · 個資雜湊",
     "local only · hmac-sha256", "洩漏檢查 · 個資檢查 · 禁用欄位")
node(760, 164, 304, 128, "rgba(45,49,66,0.03)", "rgba(45,49,66,0.30)", 1.2, "AWS", 36,
     "rgba(45,49,66,0.75)", "ic-robot", "#2d3142", "離線運算", "bedrock · sagemaker",
     "輿情標註 2,900 篇 · 訓練與回測")
node(1120, 164, 236, 176, "rgba(45,49,66,0.05)", "#4f5d75", 1.2, "S3", 32,
     "rgba(79,93,117,0.9)", "ic-bucket", "#4f5d75", "資料層", "serving/*.json",
     "算好的分數 · 約 3 MB", "private · bpa on")
node(88, 496, 256, 128, "rgba(79,93,117,0.10)", "#7a8399", 1.2, "USER", 40,
     "rgba(122,131,153,0.9)", "ic-users", "#4f5d75", "教育局稽查人員", "50 slots / week",
     "每週產出一份稽查派工單")
node(400, 496, 304, 128, "rgba(45,49,66,0.03)", "rgba(45,49,66,0.30)", 1.2, "CDN", 36,
     "rgba(45,49,66,0.75)", "ic-cdn", "#2d3142", "CloudFront + OAC", "api ttl 60s",
     "SPA 路由用 CloudFront Function")
node(760, 472, 344, 80, "rgba(45,49,66,0.05)", "#4f5d75", 1.2, "S3", 32,
     "rgba(79,93,117,0.9)", "ic-bucket", "#4f5d75", "前端靜態站", "private · no website hosting")
node(760, 572, 344, 80, "#ffffff", "#2d3142", 1.2, "API", 36,
     "rgba(45,49,66,0.8)", "ic-api", "#2d3142", "API Gateway + Lambda", "9 routes · 512mb · read-only")
a('')
a('  <!-- CALLOUTS -->')
a('  <text x="552" y="88" fill="#eb6c36" font-size="20" font-style="italic" font-family="%s" text-anchor="middle">姓名在這裡變成雜湊值，不越過這一格</text>' % SERIF)
a('  <path d="M 552 100 Q 552 128 552 156" fill="none" stroke="rgba(235,108,54,0.50)" stroke-width="1.2" stroke-dasharray="5,4"/>')
a('  <circle cx="552" cy="160" r="3" fill="#eb6c36"/>')
a('  <text x="1392" y="740" fill="#2d3142" font-size="20" font-style="italic" font-family="%s" text-anchor="end">沒有 SageMaker Endpoint — 雲端只讀算好的檔</text>' % SERIF)
a('  <path d="M 1176 728 Q 1140 700 1104 656" fill="none" stroke="rgba(45,49,66,0.40)" stroke-width="1.2" stroke-dasharray="5,4"/>')
a('  <circle cx="1104" cy="652" r="3" fill="#2d3142"/>')
a('')
a('  <!-- LEGEND -->')
a('  <line x1="48" y1="784" x2="1392" y2="784" stroke="rgba(45,49,66,0.10)" stroke-width="1"/>')
a('  <text x="48" y="812" fill="#4f5d75" font-size="11" font-family="%s" letter-spacing="0.14em">LEGEND</text>' % MONO)
for x, f, st, t in [(160, "rgba(235,108,54,0.08)", "#eb6c36", "個資邊界"),
                    (300, "rgba(45,49,66,0.05)", "#4f5d75", "S3 儲存（private）"),
                    (500, "rgba(45,49,66,0.03)", "rgba(45,49,66,0.30)", "AWS 受管服務")]:
    a('  <rect x="%d" y="800" width="24" height="16" rx="3" fill="%s" stroke="%s" stroke-width="1.2"/>' % (x, f, st))
    a('  <text x="%d" y="812" fill="#4f5d75" font-size="12" font-family="%s">%s</text>' % (x + 36, SANS, t))
for x, col, mk, t in [(672, "#2e5aa8", "arrow-link", "HTTPS 請求"),
                      (868, "#4f5d75", "arrow", "資料流"),
                      (1028, "#eb6c36", "arrow-accent", "已雜湊的資料")]:
    a('  <line x1="%d" y1="808" x2="%d" y2="808" stroke="%s" stroke-width="1.4" marker-end="url(#%s)"/>' % (x, x + 36, col, mk))
    a('  <text x="%d" y="812" fill="#4f5d75" font-size="12" font-family="%s">%s</text>' % (x + 48, SANS, t))

io.open('newsvg.txt', 'w', encoding='utf-8', newline='\n').write('\n'.join(P))
print("產生 %d 行" % len(P))
