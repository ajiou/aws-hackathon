import { Link } from "react-router-dom";
import { useApi } from "../api/queries";
import { worklistSchema } from "../api/types";
import { useUrlState } from "../hooks/useUrlState";
import {
  QueryState,
  PageHeader,
  ModelNote,
  TierBadge,
  CopyLink,
} from "../components/common";
import { isoWeek } from "../utils/format";
import s from "../styles/App.module.css";
export default function Worklist() {
  const { params, update } = useUrlState();
  const week = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/.test(params.get("week") ?? "")
    ? params.get("week")!
    : isoWeek();
  const k = [50, 100, 200].includes(Number(params.get("k")))
    ? Number(params.get("k"))
    : 50;
  const query = useApi(`/worklist?week=${week}&k=${k}`, worklistSchema);
  return (
    <>
      <div className="no-print">
        <PageHeader
          title="稽查派工單"
          description="A4 列印預覽 · 每頁兩家園所，保留稽查結果與簽章欄。"
        >
          <label>
            週次{" "}
            <input
              type="week"
              value={week}
              onChange={(e) => {
                if (e.target.value) update("week", e.target.value);
              }}
            />
          </label>
          <label>
            名額{" "}
            <select value={k} onChange={(e) => update("k", e.target.value)}>
              {[50, 100, 200].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <CopyLink />
          <button
            className={s.primary}
            disabled={!query.data?.items.length || query.data.week !== week}
            onClick={() => window.print()}
          >
            列印派工單
          </button>
        </PageHeader>
      </div>
      <QueryState query={query}>
        {(data) => {
          const pages = Array.from(
            { length: Math.ceil(data.items.length / 2) },
            (_, i) => data.items.slice(i * 2, i * 2 + 2),
          );
          return (
            <>
              {data.week !== week && (
                <p role="alert" className={s.note}>
                  目前後端回傳 {data.week}，尚未提供選定週次 {week}{" "}
                  的派工單，暫停列印。
                </p>
              )}
              {data.items.length < k && (
                <p role="status" className={`${s.note} no-print`}>
                  已取得 {data.items.length} / {k}{" "}
                  筆派工資料。資料來源尚未提供其餘項目；僅列印已提供的查核建議。
                </p>
              )}
              {!data.items.length && (
                <p className={s.note}>
                  此週次尚未產生派工單，請更換週次或稍後重試。
                </p>
              )}
              {pages.map((items, page) => (
                <section className={s.paper} data-paper key={page}>
                  <header className={s.paperHeader}>
                    <h2>新北市教保機構稽查派工單</h2>
                    <p>
                      週次：{data.week} · 產出：{data.generated_at.slice(0, 10)}
                    </p>
                    <ModelNote model={data.model} />
                  </header>
                  {items.map((item) => (
                    <article
                      className={s.workItem}
                      data-work-item
                      key={item.park_id}
                    >
                      <h3>
                        {item.seq}.{" "}
                        <Link to={`/park/${item.park_id}`}>{item.name}</Link>
                      </h3>
                      <p>
                        {item.town} · {item.institution_type} · 核定{" "}
                        {item.count_approved ?? "未提供"} 人 · 全市第{" "}
                        {item.risk.rank} 名 <TierBadge tier={item.risk.tier} />
                      </p>
                      <p>
                        TEL {item.tel || "未提供"} ·{" "}
                        {item.address || "未提供地址"}
                      </p>
                      <h4>為什麼在名單上</h4>
                      <ul>
                        {item.reasons.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                      <h4>建議查核重點</h4>
                      {item.actions.length ? (
                        <ul>
                          {item.actions.map((a, i) => (
                            <li key={i}>
                              {a.focus} — {a.why}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p>尚未提供查核建議，請依原始紀錄人工確認。</p>
                      )}
                      <p>
                        附件：裁罰紀錄 {item.attachments.punishment_count} 筆 ｜
                        評鑑歷程{" "}
                        {item.attachments.evaluation_count === null
                          ? "查無紀錄"
                          : `${item.attachments.evaluation_count} 次`}
                      </p>
                      <p className={s.signoff}>
                        稽查結果　□未發現缺失　□限期改善　□移送裁處
                        <br />
                        稽查日期 __________　簽章 __________________
                      </p>
                    </article>
                  ))}
                  <footer className={s.pageNumber}>
                    第 {page + 1} / {pages.length} 頁
                  </footer>
                </section>
              ))}
            </>
          );
        }}
      </QueryState>
    </>
  );
}
