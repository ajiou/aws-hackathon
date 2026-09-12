import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api/queries";
import { districtsSchema, type District } from "../api/types";
import { useUrlState } from "../hooks/useUrlState";
import { QueryState, PageHeader, CopyLink } from "../components/common";
import { Choropleth } from "../components/Choropleth";
import { percent } from "../utils/format";
import s from "../styles/App.module.css";
export default function Districts() {
  const query = useApi("/districts", districtsSchema);
  const [selected, setSelected] = useState("");
  const { params, setParams } = useUrlState();
  const cols: [keyof District, string][] = [
    ["town", "行政區"],
    ["park_count", "園數"],
    ["high_risk_count", "高風險數"],
    ["high_risk_ratio", "比例"],
    ["media_heat", "輿情"],
  ];
  const sort = cols.some(([key]) => key === params.get("sort"))
    ? (params.get("sort") as keyof District)
    : "high_risk_ratio";
  const dir = params.get("dir") ?? "desc";
  return (
    <>
      <PageHeader
        title="行政區風險熱力圖"
        description="比較高風險園所比例，規劃行政區稽查頻次。"
      >
        <CopyLink />
        <button onClick={() => window.print()}>列印</button>
      </PageHeader>
      <QueryState query={query}>
        {(data) =>
          data.items.length ? (
            <div className={s.twoCol}>
              <section className={s.panel}>
                <h2>29 區風險分布</h2>
                <Choropleth
                  districts={data.items}
                  selected={selected}
                  onSelect={setSelected}
                />
                {selected && (
                  <p role="status">
                    {selected} · 高風險比例{" "}
                    {percent(
                      data.items.find((d) => d.town === selected)
                        ?.high_risk_ratio ?? 0,
                    )}
                  </p>
                )}
              </section>
              <section>
                <h2>行政區排行</h2>
                <div className={s.tableWrap} data-table-wrap>
                  <table>
                    <caption className={s.srOnly}>
                      行政區高風險比例與園數
                    </caption>
                    <thead>
                      <tr>
                        {cols.map(([key, label]) => (
                          <th
                            key={key}
                            scope="col"
                            aria-sort={
                              sort === key
                                ? dir === "desc"
                                  ? "descending"
                                  : "ascending"
                                : undefined
                            }
                          >
                            <button
                              onClick={() =>
                                setParams({
                                  sort: key,
                                  dir:
                                    sort === key && dir === "desc"
                                      ? "asc"
                                      : "desc",
                                })
                              }
                            >
                              {label}{" "}
                              {sort === key
                                ? dir === "desc"
                                  ? "▼"
                                  : "▲"
                                : "↕"}
                            </button>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[...data.items]
                        .sort((a, b) => {
                          const av = a[sort],
                            bv = b[sort];
                          return (
                            (typeof av === "string"
                              ? av.localeCompare(String(bv), "zh-Hant")
                              : av - Number(bv)) * (dir === "desc" ? -1 : 1)
                          );
                        })
                        .map((d) => (
                          <tr
                            key={d.town}
                            onMouseEnter={() => setSelected(d.town)}
                            className={
                              selected === d.town ? s.highlight : undefined
                            }
                          >
                            <th scope="row">
                              <Link
                                to={`/?town=${encodeURIComponent(d.town)}`}
                                onFocus={() => setSelected(d.town)}
                              >
                                {d.town}
                              </Link>
                            </th>
                            <td className={s.num}>{d.park_count}</td>
                            <td className={s.num}>{d.high_risk_count}</td>
                            <td className={s.num}>
                              {percent(d.high_risk_ratio)}
                            </td>
                            <td className={s.num}>{d.media_heat}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          ) : (
            <p className={s.note}>尚未提供行政區彙總，請稍後重試。</p>
          )
        }
      </QueryState>
    </>
  );
}
