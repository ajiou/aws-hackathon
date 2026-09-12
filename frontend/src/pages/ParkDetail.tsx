import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi, useMeta, usePark } from "../api/queries";
import { briefSchema, type Park, type Meta } from "../api/types";
import { useUrlState } from "../hooks/useUrlState";
import {
  QueryState,
  PageHeader,
  RiskScore,
  CopyLink,
  SafeLink,
} from "../components/common";
import { number } from "../utils/format";
import s from "../styles/App.module.css";
const tabs = ["裁罰紀錄", "評鑑歷程", "收費明細", "財報"];
/** finance.metrics 的原始 key 是英文縮寫，稽查人員看不懂 fee_deviation 是什麼。
 *  三個同儕群各有各的指標集（收費 6 項／公立-獨立決算 10 項／非營利 8 項），
 *  這裡一次涵蓋。年度欄不當成指標顯示，它已經在標題列上。 */
const financeMetricNames: Record<string, string> = {
  fee_deviation: "收費偏離度",
  fee_consistency: "收費一致性",
  fee_completeness: "收費完整性",
  total_full_year: "全年全日班總收費",
  peer_median_full_year: "同儕中位數",
  deviation_pct: "偏離同儕中位數 %",
  deficit_ratio: "短絀比率",
  enroll_ratio: "註冊率",
  expense_deviation: "支出偏離度",
  tuition_exec_rate: "學費執行率",
  cash_decrease_ratio: "現金減少比率",
  debt_ratio: "負債比率",
  networth_decline: "淨值下降 %",
  enroll_decline: "註冊人數下降 %",
  over_enroll: "超收人數",
  students: "在園人數",
  count_approved: "核定人數",
  income_exec_deviation: "收入執行偏離度",
  expense_exec_deviation: "支出執行偏離度",
  personnel_exec_rate: "人事費執行率",
  teacher_salary_exec_rate: "教師薪資執行率",
  overtime_exec_rate: "加班費執行率",
  substitute_exec_rate: "代課費執行率",
};
const financeYearKeys = new Set(["fiscal_year", "school_year"]);
export function Timeline({ park, cutoff }: { park: Park; cutoff: string }) {
  const [expanded, setExpanded] = useState(false);
  const sorted = [...park.timeline]
    .sort((a, b) => b.date.localeCompare(a.date))
    .map((item, index) => ({ ...item, index }));
  const render = (after: boolean) => (
    <ol className={s.timeline}>
      {sorted
        .filter((t) => t.date >= cutoff === after)
        .map((t) => (
          <li
            key={t.index}
            hidden={!expanded && t.index >= 8}
            data-timeline-item
            className={after ? s.after : ""}
            style={
              {
                "--severity": `var(--c-sev-${/不當|性平/.test(t.category) ? 5 : /食安|設施/.test(t.category) ? 4 : /超收|師生|師資|交通/.test(t.category) ? 3 : /收費/.test(t.category) ? 2 : 1})`,
              } as React.CSSProperties
            }
          >
            <div>
              <time>{t.date}</time> · <strong>{t.category}</strong> ·{" "}
              {t.fine === null ? t.penalty_raw : `罰鍰 ${number(t.fine)} 元`}
              {after && <small>〔標籤期間〕</small>}
            </div>
            <p>{t.law}</p>
          </li>
        ))}
    </ol>
  );
  return (
    <>
      <p className={s.note}>切點後的紀錄屬標籤期間，未用於模型特徵。</p>
      {/* 圓點顏色本來就依違規類別分五級，但畫面上沒有任何地方說過，
          深淺看起來像隨機的。 */}
      <ul className={s.severityLegend} aria-label="圓點顏色代表違規類別嚴重度">
        {[
          [5, "不當對待／性平"],
          [4, "食安／設施"],
          [3, "超收／師生比／師資／交通"],
          [2, "收費"],
          [1, "其他行政"],
        ].map(([level, label]) => (
          <li key={level}>
            <span style={{ background: `var(--c-sev-${level})` }} />
            {label}
          </li>
        ))}
      </ul>
      {render(true)}
      <div className={s.cutoff}>切點 {cutoff}</div>
      {render(false)}
      {sorted.length > 8 && (
        <button aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
          {expanded ? "收合" : `展開其餘 ${sorted.length - 8} 筆`}
        </button>
      )}
      {!sorted.length && <p>目前資料未提供裁罰紀錄，不代表無風險。</p>}
    </>
  );
}
/** 輿情。分數那條路必須守切點，這一面板刻意不守——欣勵德 2026-04 的虐童案
 *  （44 篇報導、園長遭聲押）全部落在切點之後，舊版頁面只寫「未偵測到明文
 *  點名之報導」，等於把稽查人員最需要知道的事藏起來。切點後的報導標明
 *  〔未計入分數〕，讓兩件事各自成立：分數沒有洩漏，人看得到最新狀況。 */
export function MediaPanel({ park, cutoff }: { park: Park; cutoff: string }) {
  const [expanded, setExpanded] = useState(false);
  const coverage = park.media_coverage ?? [];
  const recent = coverage.filter((c) => c.is_after_cutoff).length;
  // 同一起事件常被十幾家媒體同日轉載，全部攤開會把其他事件擠到看不見。
  const shown = expanded ? coverage : coverage.slice(0, 5);
  return (
    <section className={s.panel}>
      <h2>輿情訊號</h2>
      {park.media.has_signal ? (
        <p>
          本園 SRI {park.media.sri} · 切點前最近事件{" "}
          {park.media.last_negative_at ?? "未提供日期"}
        </p>
      ) : (
        <p>
          切點（{cutoff}）前未偵測到明文點名之報導
          {recent > 0 ? "，但切點之後有：" : "。未被報導不代表無風險。"}
        </p>
      )}
      {coverage.length > 0 && (
        <ul className={s.coverageList}>
          {shown.map((c, i) => (
            <li key={i}>
              <span className={s.rowMeta}>
                {c.date} · {c.outlet ?? "來源未提供"}
                {c.event_type ? ` · ${c.event_type}` : ""}
                {c.is_after_cutoff && (
                  <b className={s.afterCutoffTag}>〔未計入分數〕</b>
                )}
              </span>
              {c.url ? <SafeLink href={c.url}>{c.title}</SafeLink> : c.title}
            </li>
          ))}
        </ul>
      )}
      {coverage.length > 5 && (
        <button
          aria-expanded={expanded}
          data-print-expand
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "收合" : `展開其餘 ${coverage.length - 5} 則`}
        </button>
      )}
      {coverage.length > 0 && (
        <p className={s.note}>
          報導由關鍵字比對掛回園所，僅供人工查證，不參與打分。
        </p>
      )}
      {/* 熱度 0 的區給名次是誤導：29 區裡有 18 區熱度都是 0，
          「全市第 12 名」看起來像第 12 熱門，其實是並列 0 的任意排序。 */}
      <p className={s.rowMeta}>
        所在區熱度 {park.media.town_heat_per_park.toFixed(2)} / 園
        {park.media.town_heat_per_park > 0
          ? ` · 全市第 ${park.media.town_heat_rank ?? "未提供"} 名`
          : "（本區無報導，不排名次）"}
      </p>
    </section>
  );
}
function Content({ park, meta }: { park: Park; meta: Meta }) {
  const brief = useApi(
    `/parks/${encodeURIComponent(park.park_id)}/brief`,
    briefSchema,
  );
  const { params, update } = useUrlState();
  const active = Math.min(3, Math.max(0, Number(params.get("tab")) || 0));
  const has = [
    park.timeline.length,
    park.evaluations?.length,
    park.fees?.length,
    park.finance?.length,
  ];
  return (
    <div className={s.limited}>
      <PageHeader
        title={park.name}
        description={`${park.town} · ${park.institution_type} · 核定 ${park.count_approved ?? "未提供"} 人 · ${park.tel || "未提供電話"}${!park.is_active ? " · 已停辦" : ""}`}
      >
        <Link to="/">返回總覽</Link>
        <CopyLink />
        <button onClick={() => window.print()}>列印分析</button>
      </PageHeader>
      <p>
        {park.address} ·{" "}
        {park.established_at ? `立案 ${park.established_at}` : "未提供立案日期"}
        {park.lon === null || park.lat === null ? " · 無座標資料" : ""}
      </p>
      {/* 由上到下三段等寬的方形結構：風險總分橫幅 → 建議查核重點／輿情訊號
          並排 → 分頁。窄螢幕時中段自動疊成一欄（見 App.module.css .pair）。 */}
      <RiskScore park={park} meta={meta} />
      <div className={s.pair}>
        <section className={s.panel}>
          <h2>建議查核重點</h2>
          <QueryState query={brief}>
            {(data) => (
              <>
                {data.summary && <p>{data.summary}</p>}
                {data.actions.length ? (
                  <ul>
                    {data.actions.map((a, i) => (
                      <li key={i}>
                        <strong>{a.focus}</strong> — {a.why}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={s.note}>
                    此園尚未提供查核建議，請依裁罰與評鑑原始紀錄人工確認。
                  </p>
                )}
                <small>
                  來源：
                  {data.source === "llm" ? "離線文字摘要" : "預先產生的模板"}
                  。文字摘要不參與打分。
                </small>
              </>
            )}
          </QueryState>
        </section>
        <MediaPanel park={park} cutoff={meta.cutoff} />
      </div>
      <div className={s.tabs} role="tablist" aria-label="園所資料">
        {tabs.map((tab, i) => (
          <button
            key={tab}
            id={`tab-${i}`}
            role="tab"
            aria-selected={active === i}
            aria-controls={`panel-${i}`}
            tabIndex={active === i ? 0 : -1}
            className={!has[i] ? s.missingTab : undefined}
            onClick={() => update("tab", String(i), false, true)}
            onKeyDown={(e) => {
              const index =
                e.key === "ArrowRight"
                  ? (i + 1) % 4
                  : e.key === "ArrowLeft"
                    ? (i + 3) % 4
                    : e.key === "Home"
                      ? 0
                      : e.key === "End"
                        ? 3
                        : -1;
              if (index >= 0) {
                e.preventDefault();
                update("tab", String(index), false, true);
                document.getElementById(`tab-${index}`)?.focus();
              }
            }}
          >
            {tab} {has[i] ? `(${has[i]})` : "（無明細）"}
          </button>
        ))}
      </div>
      {tabs.map((tab, i) => (
        <section
          key={tab}
          role="tabpanel"
          id={`panel-${i}`}
          aria-labelledby={`tab-${i}`}
          hidden={active !== i}
          className={s.panel}
        >
          <h2>
            {tab}
            {/* 列印時各區塊標題都帶園名，印出來的紙才認得出是哪一間園。
                螢幕上不顯示。 */}
            <span className={s.printIdent} data-print-ident>
              {" · "}
              {park.name} · 切點 {meta.cutoff} · {meta.version}
            </span>
          </h2>
          {i === 0 && <Timeline park={park} cutoff={meta.cutoff} />}{" "}
          {i === 1 &&
            (park.evaluations?.length ? (
              <>
                <p className={s.note}>
                  由新到舊。同一學年度可能有「基礎評鑑→追蹤評鑑→數次行政處分」
                  的升級鏈，風險原因中的次數即由此累計。
                </p>
                <div className={s.tableWrap}>
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">學年度</th>
                        <th scope="col">完成日</th>
                        <th scope="col">類別</th>
                        <th scope="col">結果</th>
                      </tr>
                    </thead>
                    <tbody>
                      {park.evaluations.map((e, j) => (
                        <tr key={j}>
                          <td>{e.year}</td>
                          <td>{e.date ?? "未提供"}</td>
                          <td>{e.kind ?? "未提供"}</td>
                          <td>{e.result}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p>
                查無切點前之評鑑明細；可能為新立案園所，或資料來源尚未提供完整紀錄。
              </p>
            ))}
          {i === 2 &&
            (park.fees?.length ? (
              <>
                <p className={s.note}>
                  收費表是核准公告價格；偏離僅作弱訊號，不直接視為違規。
                </p>
                <table>
                  <thead>
                    <tr>
                      <th scope="col">年度</th>
                      <th scope="col">項目</th>
                      <th scope="col">期間</th>
                      <th scope="col">金額</th>
                    </tr>
                  </thead>
                  <tbody>
                    {park.fees.map((f, j) => (
                      <tr key={j}>
                        <td>{f.year}</td>
                        <td>{f.item}</td>
                        <td>{f.period ?? "未提供"}</td>
                        <td className={s.num}>
                          {f.amount === null ? "——" : number(f.amount)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : (
              <p>
                {park.has_fee
                  ? "本園有收費資料，但本次回應尚未提供明細。"
                  : "收費明細僅公立幼兒園公告，本園無此資料。"}
              </p>
            ))}
          {i === 3 &&
            (park.finance?.length ? (
              <>
                <p className={s.note}>
                  營運維度尚無足夠裁罰樣本可驗證，以下數字供人工複查，不等同違規。
                </p>
                <ul>
                  {park.finance.map((f, j) => (
                    <li key={j}>
                      {/* 302 筆裡只有 46 筆真的有 PDF。其餘原本一樣包在
                          SafeLink 裡，產生的是沒有 href 的 <a>——看起來
                          可以點、點了沒反應。有連結才給連結。 */}
                      {(f.pdf_url ?? f.url) ? (
                        <SafeLink href={f.pdf_url ?? f.url}>
                          {f.year === null ? "" : `${f.year} 學年度 `}
                          {f.title ?? "財務報告 PDF"}（連結效期 15 分鐘）
                        </SafeLink>
                      ) : (
                        <>
                          {/* 公立-附設園沒有自己的學年度（決算併入所屬學校），
                              不要印成「null 學年度」。 */}
                          {f.year === null ? "" : `${f.year} 學年度 · `}
                          營運分數 {f.operation_score ?? "未計算"}
                          <span className={s.rowMeta}> · 無公開 PDF</span>
                        </>
                      )}
                      {f.metrics && (
                        <dl className={s.metrics}>
                          {Object.entries(f.metrics)
                            .filter(
                              ([k, v]) => v !== null && !financeYearKeys.has(k),
                            )
                            .map(([k, v]) => (
                              <div key={k}>
                                <dt>{financeMetricNames[k] ?? k}</dt>
                                <dd>{number(v as number)}</dd>
                              </div>
                            ))}
                        </dl>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p>
                {park.institution_type === "私立"
                  ? "私立幼兒園依法不需公告財務報告"
                  : park.peer_group === "公立-附設"
                    ? "本園為附設幼兒園，財務併入所屬學校，營運分數僅依收費明細計算"
                    : (park.dimensions.operation.note ??
                      "本次資料未提供財務報告，請向資料來源確認。")}
              </p>
            ))}
        </section>
      ))}
    </div>
  );
}
export default function ParkDetail() {
  const { id = "" } = useParams();
  const query = usePark(id);
  const meta = useMeta();
  return (
    <QueryState query={query}>
      {(park) => (
        <QueryState query={meta}>
          {(data) => <Content park={park} meta={data} />}
        </QueryState>
      )}
    </QueryState>
  );
}
