import { lazy, Suspense } from "react";
import {
  ListFilter,
  MapPin,
  Layers,
  RotateCcw,
  Check,
  Info,
} from "lucide-react";
import { useApi } from "../api/queries";
import { districtsSchema, type MapData } from "../api/types";
import { filterMapParks, useMapParks } from "../api/map";
import { useUrlState } from "../hooks/useUrlState";
import {
  QueryState,
  PageHeader,
  Skeleton,
  CopyLink,
} from "../components/common";
import { ParkDrawer } from "../components/ParkDrawer";
import Overview from "./Overview";
import { Button } from "../components/ui/button";
import { cn } from "../lib/utils";
import { percent } from "../utils/format";
import s from "../styles/App.module.css";
const MapCanvas = lazy(() => import("../components/MapCanvas"));
const types = ["公立", "非營利", "私立"] as const;
const typeColors = {
  公立: "bg-blue-600",
  非營利: "bg-teal-600",
  私立: "bg-violet-600",
};
const heatBands = ["0–2%", "2–4%", "4–6%", "6–8%", "8% 以上"];

function Distribution({ data }: { data: MapData }) {
  const { params, update, clear, setParams } = useUrlState();
  const mode = params.get("mode") === "districts" ? "districts" : "points";
  const districts = useApi("/districts", districtsSchema);
  const visible = filterMapParks(data, params);
  const selectedTypes = params.getAll("type");
  const town = params.get("town") ?? "";
  const id = params.get("selected") ?? "";
  const selected = visible.features.find((f) => f.properties.park_id === id);
  function filter(key: string, value: string | string[]) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete(key);
      next.delete("selected");
      for (const v of Array.isArray(value) ? value : [value])
        if (v) next.append(key, v);
      return next;
    });
  }
  const towns = [
    ...new Set(
      data.features
        .map((f) => f.properties.town)
        .filter((t): t is string => !!t),
    ),
  ].sort((a, b) => a.localeCompare(b, "zh-Hant"));
  const hasFilters = ["q", "town", "tier", "type"].some((key) =>
    params.has(key),
  );
  const townStats = districts.data?.items.find((d) => d.town === town);
  return (
    <>
      <div
        className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-border bg-background p-3"
        data-filters
        aria-label="地圖篩選"
      >
        <span className="flex items-center gap-2 text-sm font-medium">
          <ListFilter
            className="size-4 text-muted-foreground"
            aria-hidden="true"
          />
          設立別
        </span>
        <div
          className="flex flex-wrap gap-1"
          role="group"
          aria-label="設立別篩選"
        >
          <Button
            variant={!selectedTypes.length ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={!selectedTypes.length}
            onClick={() => filter("type", [])}
          >
            全部
          </Button>
          {types.map((type) => (
            <Button
              key={type}
              variant={selectedTypes.includes(type) ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={selectedTypes.includes(type)}
              onClick={() =>
                filter(
                  "type",
                  selectedTypes.includes(type)
                    ? selectedTypes.filter((t) => t !== type)
                    : [...selectedTypes, type],
                )
              }
            >
              <span
                className={cn("size-2 rounded-full", typeColors[type])}
                aria-hidden="true"
              />
              {type}
              {selectedTypes.includes(type) && <Check className="size-3" />}
            </Button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="sr-only">行政區篩選</span>
          <select
            value={town}
            onChange={(e) => filter("town", e.target.value)}
            className="h-9 max-w-36 rounded-md border-input py-1"
          >
            <option value="">全部行政區</option>
            {towns.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="sr-only">風險分級篩選</span>
          <select
            value={params.get("tier") ?? ""}
            onChange={(e) => filter("tier", e.target.value)}
            className="h-9 rounded-md border-input py-1"
          >
            <option value="">全部風險</option>
            {["高", "中", "低"].map((tier) => (
              <option key={tier} value={tier}>
                {tier}風險
              </option>
            ))}
          </select>
        </label>
        {hasFilters && (
          <Button
            variant="ghost"
            size="icon"
            className="size-9"
            aria-label="清除全部篩選"
            onClick={() => clear()}
          >
            <RotateCcw />
          </Button>
        )}
      </div>
      <div className={s.mapLayout}>
        <section
          className="overflow-hidden rounded-xl border border-border bg-background shadow-sm"
          aria-label="園所風險地圖"
        >
          <div className={s.mapViewport}>
            <Suspense fallback={<Skeleton />}>
              <MapCanvas
                data={visible}
                districts={districts.data?.items ?? []}
                mode={mode}
                selectedTown={town}
                onSelect={(parkId) => update("selected", parkId, false)}
                onSelectTown={(name) =>
                  filter("town", name === town ? "" : name)
                }
              />
            </Suspense>
            <div
              className="absolute right-3 top-3 z-10 inline-flex rounded-lg border border-border bg-background/95 p-1 shadow-md"
              role="group"
              aria-label="圖層切換"
            >
              <Button
                variant={mode === "points" ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={mode === "points"}
                onClick={() => filter("mode", "points")}
              >
                <MapPin />
                園所分布
              </Button>
              <Button
                variant={mode === "districts" ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={mode === "districts"}
                onClick={() => filter("mode", "districts")}
              >
                <Layers />
                行政區熱力
              </Button>
            </div>
            {mode === "points" && !visible.features.length && (
              <div
                className="absolute inset-x-4 top-48 z-10 mx-auto max-w-sm rounded-xl border border-border bg-background p-5 text-center shadow-md"
                role="status"
              >
                <h2>沒有符合條件的園所</h2>
                <p className="text-muted-foreground">
                  請調整設立別、行政區或搜尋關鍵字。
                </p>
                <Button variant="outline" onClick={() => clear()}>
                  清除全部篩選
                </Button>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
            <span className="text-sm" aria-live="polite">
              {mode === "districts" ? (
                <>
                  {town ? (
                    <>
                      已選 <strong>{town}</strong>
                      {townStats && (
                        <span className="text-muted-foreground">
                          {" "}
                          · 園數 {townStats.park_count} · 高風險{" "}
                          {townStats.high_risk_count} ·{" "}
                          {percent(townStats.high_risk_ratio)}
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="text-muted-foreground">
                      點選行政區，右側顯示該區風險預測
                    </span>
                  )}
                </>
              ) : (
                <>
                  顯示{" "}
                  <strong>{visible.features.length.toLocaleString()}</strong>{" "}
                  間幼兒園
                  {params.get("q") && (
                    <span className="text-muted-foreground">
                      {" "}
                      · 搜尋「{params.get("q")}」
                    </span>
                  )}
                </>
              )}
            </span>
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              {mode === "districts" ? (
                <>
                  <span>顏色：高風險園所占比</span>
                  {heatBands.map((label, i) => (
                    <span key={label} className="flex items-center gap-1.5">
                      <i
                        className={s.swatch}
                        style={{ background: `var(--c-heat-${i + 1})` }}
                      />
                      {label}
                    </span>
                  ))}
                </>
              ) : (
                <>
                  <span>點位顏色：設立別</span>
                  {types.map((type) => (
                    <span key={type} className="flex items-center gap-1.5">
                      <i
                        className={cn("size-2 rounded-full", typeColors[type])}
                      />
                      {type}
                    </span>
                  ))}
                  <span>叢集：園所數量</span>
                </>
              )}
            </div>
          </div>
        </section>
        <div className={s.districtOverview}>
          {mode === "points" && id && selected ? (
            <ParkDrawer
              inline
              id={id}
              name={selected.properties.name}
              onClose={() => update("selected", "", false)}
            />
          ) : (
            <section aria-label="教保機構風險總覽">
              <Overview embedded />
            </section>
          )}
        </div>
      </div>
      {mode === "points" && (
        <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
          <p className="m-0 flex max-w-2xl items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            無座標園所可由總覽搜尋。風險分級代表查核優先序，低風險不代表安全或合格。
          </p>
          <label
            className="flex w-full max-w-sm flex-col gap-1.5 text-xs text-muted-foreground"
            htmlFor="map-park-select"
          >
            選擇園所（鍵盤操作）
            <select
              id="map-park-select"
              className="w-full text-sm"
              value={selected ? id : ""}
              onChange={(e) => update("selected", e.target.value, false)}
            >
              <option value="">選擇園所，查看基本資料</option>
              {visible.features.map((f) => (
                <option key={f.properties.park_id} value={f.properties.park_id}>
                  {f.properties.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {mode === "points" && id && !selected && (
        <p role="status" className={s.note}>
          所選園所不在目前的篩選範圍，請調整篩選或重新選擇。
        </p>
      )}
    </>
  );
}
export default function MapPage() {
  const query = useMapParks();
  return (
    <>
      <PageHeader
        title="園所風險地圖"
        description="一張圖切換園所分布與行政區熱力，右側同步顯示風險資訊。"
      >
        <CopyLink />
      </PageHeader>
      <QueryState query={query}>
        {(data) => <Distribution data={data} />}
      </QueryState>
    </>
  );
}
