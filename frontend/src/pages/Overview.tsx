import { Link } from "react-router-dom";
import { useApi, usePark } from "../api/queries";
import { parksSchema, type ParkRow } from "../api/types";
import { useUrlState } from "../hooks/useUrlState";
import { FilterBar, EmptyState } from "../components/FilterBar";
import {
  PageHeader,
  CopyLink,
  QueryState,
  ReasonList,
  TierBadge,
  Hint,
} from "../components/common";
import { number } from "../utils/format";
import s from "../styles/App.module.css";
function Row({ row }: { row: ParkRow }) {
  const details = usePark(row.park_id, !row.reasons);
  const reasons = row.reasons ?? details.data?.reasons;
  return (
    <tr className={!row.is_active ? s.inactive : undefined}>
      <td className={s.num}>{row.risk.rank}</td>
      <th scope="row" className={s.nameCell}>
        <Link to={`/park/${row.park_id}`}>{row.name}</Link>
        {!row.is_active && <p>已停辦</p>}
      </th>
      <td>{row.town}</td>
      <td>{row.institution_type}</td>
      <td className={s.num}>
        {reasons?.length && row.risk.score !== null
          ? row.risk.score.toFixed(1)
          : "——"}
      </td>
      <td>
        <TierBadge tier={row.risk.tier} />
      </td>
      <td className={s.num}>{row.pun_count}</td>
      <td>
        {row.has_finance_flag ? (
          <Hint text="有財務旗標，不計入風險分數，僅供人工複查；詳見單園分析。" />
        ) : (
          "—"
        )}
      </td>
      <td>
        {reasons ? (
          <ReasonList reasons={reasons} />
        ) : (
          <QueryState query={details}>
            {(p) => <ReasonList reasons={p.reasons} />}
          </QueryState>
        )}
      </td>
    </tr>
  );
}
export default function Overview({ embedded = false }: { embedded?: boolean }) {
  const { params, update, setParams } = useUrlState();
  const parkParams = new URLSearchParams(params);
  parkParams.delete("mode");
  parkParams.delete("selected");
  const query = useApi(`/parks?${parkParams}`, parksSchema);
  const sort = params.get("sort") ?? "risk",
    dir = params.get("dir") ?? "desc";
  function sortBy(key: string) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("sort", key);
      next.set("dir", sort === key && dir === "desc" ? "asc" : "desc");
      next.delete("page");
      return next;
    });
  }
  const headers = [
    ["名次", "risk"],
    ["園名", "name"],
    ["行政區", ""],
    ["設立別", ""],
    ["風險分", "risk"],
    ["分級", ""],
    ["裁罰次數", "pun_count"],
    ["旗標", ""],
    ["上榜原因", ""],
  ];
  return (
    <>
      <PageHeader
        headingLevel={embedded ? 2 : 1}
        title="教保機構風險總覽"
        description="搜尋園所、檢視原因，安排本週稽查。低風險僅代表本週不列入優先稽查。"
      >
        <CopyLink />
        <button onClick={() => window.print()}>列印</button>
      </PageHeader>
      <FilterBar />
      <QueryState query={query}>
        {(data) =>
          !data.items.length ? (
            <EmptyState />
          ) : (
            <>
              <div className={s.tableWrap} data-table-wrap>
                <table className={s.dataTable}>
                  <caption className={s.srOnly}>教保機構風險搜尋結果</caption>
                  <thead>
                    <tr>
                      {headers.map(([label, key]) => (
                        <th
                          key={label}
                          scope="col"
                          aria-sort={
                            key && sort === key
                              ? dir === "desc"
                                ? "descending"
                                : "ascending"
                              : undefined
                          }
                        >
                          {key ? (
                            <button onClick={() => sortBy(key)}>
                              {label}{" "}
                              {sort === key
                                ? dir === "desc"
                                  ? "▼"
                                  : "▲"
                                : "↕"}
                            </button>
                          ) : (
                            label
                          )}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((row) => (
                      <Row key={row.park_id} row={row} />
                    ))}
                  </tbody>
                </table>
              </div>
              <div className={s.pagination} data-pagination>
                <span>
                  第 {number((data.page - 1) * data.size + 1)}–
                  {number(Math.min(data.page * data.size, data.total))} 筆，共{" "}
                  {number(data.total)} 筆
                </span>
                <div className={s.actions}>
                  <button
                    disabled={data.page <= 1}
                    onClick={() => update("page", String(data.page - 1), false)}
                  >
                    上一頁
                  </button>
                  <label>
                    頁碼{" "}
                    <select
                      value={data.page}
                      onChange={(e) => update("page", e.target.value, false)}
                    >
                      {Array.from(
                        { length: Math.ceil(data.total / data.size) },
                        (_, i) => (
                          <option key={i} value={i + 1}>
                            {i + 1}
                          </option>
                        ),
                      )}
                    </select>
                  </label>
                  <button
                    disabled={data.page * data.size >= data.total}
                    onClick={() => update("page", String(data.page + 1), false)}
                  >
                    下一頁
                  </button>
                  <label>
                    每頁{" "}
                    <select
                      value={data.size}
                      onChange={(e) => update("size", e.target.value)}
                    >
                      {[50, 100, 200].map((n) => (
                        <option key={n}>{n}</option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
            </>
          )
        }
      </QueryState>
    </>
  );
}
