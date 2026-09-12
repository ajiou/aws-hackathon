import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi, useMeta, usePark } from "../api/queries";
import { briefSchema, type Park, type Meta } from "../api/types";
import { useUrlState } from "../hooks/useUrlState";
import {
  QueryState,
  PageHeader,
  RiskScore,
  FinanceFlags,
  CopyLink,
  SafeLink,
} from "../components/common";
import { number } from "../utils/format";
import s from "../styles/App.module.css";
const tabs = ["裁罰紀錄", "評鑑歷程", "收費明細", "財報"];
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
      <div className={s.twoCol}>
        <div>
          <RiskScore park={park} meta={meta} />
          <section className={s.panel}>
            <h2>輿情訊號</h2>
            {park.media.has_signal ? (
              <>
                <p>
                  本園 SRI {park.media.sri} · 最近事件{" "}
                  {park.media.last_negative_at ?? "未提供日期"}
                </p>
                {park.media.article_count !== undefined && (
                  <p>
                    {park.media.article_count} 篇報導 /{" "}
                    {park.media.event_count ?? "未提供"} 起事件
                  </p>
                )}
              </>
            ) : (
              <p>未偵測到明文點名之報導。未被報導不代表無風險。</p>
            )}
            <p>
              所在區熱度 {park.media.town_heat_per_park} / 園 · 全市第{" "}
              {park.media.town_heat_rank ?? "未提供"} 名
            </p>
          </section>
        </div>
        <div>
          <section className={s.panel}>
            <FinanceFlags flags={park.finance_flags} />
          </section>
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
        </div>
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
            onClick={() => update("tab", String(i), false)}
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
                update("tab", String(index), false);
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
          <h2>{tab}</h2>
          {i === 0 && <Timeline park={park} cutoff={meta.cutoff} />}{" "}
          {i === 1 &&
            (park.evaluations?.length ? (
              <table>
                <thead>
                  <tr>
                    <th scope="col">年度</th>
                    <th scope="col">類別</th>
                    <th scope="col">結果</th>
                  </tr>
                </thead>
                <tbody>
                  {park.evaluations.map((e, j) => (
                    <tr key={j}>
                      <td>{e.year}</td>
                      <td>{e.kind ?? "未提供"}</td>
                      <td>{e.result}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
                <p>財報連結效期 15 分鐘；失效時請重新整理本頁。</p>
                <ul>
                  {park.finance.map((f, j) => (
                    <li key={j}>
                      <SafeLink href={f.pdf_url ?? f.url}>
                        {f.year} 學年度 {f.title ?? "財務報告 PDF"}
                      </SafeLink>
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
