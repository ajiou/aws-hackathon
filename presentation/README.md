# 簡報素材

兩版架構圖，各有取捨。**兩版都保留**，用在不同場合。

| | `architecture.*`（diagram-design） | `archify-architecture.*`（archify） |
|---|---|---|
| 產生方式 | 手刻 SVG，`architecture_build.py` | JSON 規格 → 渲染器 |
| 原始檔 | 22 KB HTML | **3.6 KB JSON** |
| 輸出 | PNG 2880×1696、SVG、HTML | PNG 2414×1557、互動 HTML 810 KB |
| 兩個設計決定 | 斜體邊註（marginalia） | **虛線邊界框（結構）** |
| 成效數據 | ✅ 上方數據帶 + 三張說明卡 | ❌ 無 |
| 幾何驗證 | 自寫檢查 + skill self-check | **9 項 artifact 檢查，不過就不出圖** |
| 互動 | 無 | Light/Dark、Present、Export、縮放、路徑追蹤 |
| 色彩 | 1 個 accent + 中性色 | 依元件類型 5 色 |

## 什麼時候用哪一版

**投影片靜態頁 → `architecture.png`**
數據帶（1,178 園 / Precision@50 28.0% / 2.65× / 0 個 endpoint / 0 筆姓名上雲）與三張說明卡，
是評審要看的證據。archify 版沒有這些。

**現場 Demo → `archify-architecture.html`**
Present 模式、Light/Dark、點擊追蹤關聯路徑。而且**兩個設計決定是真正的框**：

- 粉色虛線框「本機執行 — 自然人姓名不越過此界」實際圈住 `六個公開資料源` 與 `ETL`
- 琥珀色虛線框「AWS us-west-2 — 無線上推論，雲端只讀算好的靜態檔」圈住其餘五個元件

比 diagram-design 版的斜體邊註強——邊界是結構，邊註只是註解。

## 重新產生

```bash
# diagram-design 版
python presentation/architecture_build.py      # 產 SVG 區塊
python presentation/architecture_export.py     # 產 PNG

# archify 版（需先裝 skill：npx skills add tt-a1i/archify -g）
cd ~/.claude/skills/archify
node bin/archify.mjs validate architecture <此目錄>/archify-architecture.json --quality showcase --json
node bin/archify.mjs deliver  architecture <此目錄>/archify-architecture.json <此目錄>/archify-architecture.html --quality showcase --json
```

archify 的 `deliver` 是唯一的驗收指令，非零離開碼就是失敗，不可當成成功。

## archify 版已知的三個小問題

1. `已雜湊為 owner_key` 標籤浮在畫布中段空白處（連線繞路所致）
2. 左下有一塊明顯留白
3. `tag` 欄位（`1,178 園`、`private`、`本機執行`）在 classic preset 下沒有視覺呈現

前兩項可再調 `pos`，第三項是渲染器行為。皆不影響正確性。

## 語言

archify 的 `meta.locale` 只支援 `en` 與 `zh-CN`。本專案是繁體中文，
依其契約**省略 `meta.locale`**，因此**檢視器自身的 UI（Light / Present / Export 等按鈕）與 `<html lang>` 會落回英文**。
圖上的內容全部是我們自己撰寫的繁體中文，渲染器不會翻譯。
