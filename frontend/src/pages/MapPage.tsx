import { lazy, Suspense } from "react";
import { useApi, useMeta, usePark } from "../api/queries";
import { mapSchema, districtsSchema } from "../api/types";
import { useUrlState } from "../hooks/useUrlState";
import { FilterBar } from "../components/FilterBar";
import {
  QueryState,
  PageHeader,
  ParkCard,
  Skeleton,
  TierBadge,
  CopyLink,
} from "../components/common";
import { Choropleth } from "../components/Choropleth";
import s from "../styles/App.module.css";
const MapCanvas = lazy(() => import("../components/MapCanvas"));
function Selected({ id }: { id: string }) {
  const park = usePark(id);
  return <QueryState query={park}>{(p) => <ParkCard park={p} />}</QueryState>;
}
export default function MapPage() {
  const { params, update } = useUrlState();
  const filter = new URLSearchParams();
  for (const key of ["town", "tier"])
    for (const v of params.getAll(key)) filter.append(key, v);
  const query = useApi(`/map?${filter}`, mapSchema);
  const meta = useMeta();
  const districts = useApi("/districts", districtsSchema);
  const mode = params.get("mode") ?? "points";
  const id = params.get("selected") ?? "";
  return (
    <>
      <PageHeader
        title="園所風險地圖"
        description="依區域安排路線；叢集顏色代表其中最高風險級別。"
      >
        <label>
          顯示模式{" "}
          <select
            value={mode}
            onChange={(e) => update("mode", e.target.value, false)}
          >
            <option value="points">點位模式</option>
            <option value="districts">行政區模式</option>
          </select>
        </label>
        <CopyLink />
      </PageHeader>
      <FilterBar
        map
        total={query.data?.features.length}
        population={meta.data?.population ?? 1}
      />
      <QueryState query={query}>
        {(data) => (
          <>
            <div className={s.mapLayout}>
              <section>
                {mode === "districts" ? (
                  <div className={s.panel}>
                    <QueryState query={districts}>
                      {(d) => (
                        <Choropleth
                          districts={d.items}
                          selected={params.get("hover") ?? ""}
                          onSelect={() => {}}
                        />
                      )}
                    </QueryState>
                  </div>
                ) : (
                  <Suspense fallback={<Skeleton />}>
                    <MapCanvas
                      data={data}
                      onSelect={(id) => update("selected", id, false)}
                    />
                  </Suspense>
                )}
                <div className={s.legend}>
                  {(["高", "中", "低"] as const).map((t) => (
                    <TierBadge key={t} tier={t} />
                  ))}
                </div>
                <p className={s.muted}>
                  無座標園所不顯示於地圖，仍可由總覽搜尋。低風險不代表安全或合格。
                </p>
              </section>
              <aside className={s.mapSide} aria-label="選取園所資訊">
                <div className={s.panel}>
                  <h2>園所資訊</h2>
                  <p aria-live="polite">
                    目前篩選範圍共 {data.features.length} 個點位。
                  </p>
                  <label>
                    選擇園所（鍵盤操作）
                    <select
                      style={{ width: "100%" }}
                      value={id}
                      onChange={(e) =>
                        update("selected", e.target.value, false)
                      }
                    >
                      <option value="">請選擇園所</option>
                      {data.features.map((f) => (
                        <option
                          key={f.properties.park_id}
                          value={f.properties.park_id}
                        >
                          {f.properties.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {id && (
                    <button onClick={() => update("selected", "", false)}>
                      關閉園所資訊
                    </button>
                  )}
                </div>
                {id ? (
                  <Selected id={id} />
                ) : (
                  <p className={s.note}>
                    點選地圖點位或使用園所選單，查看風險原因與完整分析。
                  </p>
                )}
              </aside>
            </div>
            {!data.features.length && (
              <p className={s.note}>
                目前篩選沒有具座標的園所，請清除篩選，或改用總覽查看。
              </p>
            )}
          </>
        )}
      </QueryState>
    </>
  );
}
