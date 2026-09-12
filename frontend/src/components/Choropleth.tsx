import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import type { FeatureCollection, Geometry, Position } from "geojson";
import type { District } from "../api/types";
import { QueryState } from "./common";
import { percent } from "../utils/format";
import s from "../styles/App.module.css";
export const heatLevel = (ratio: number) =>
  ratio < 0.02 ? 1 : ratio < 0.04 ? 2 : ratio < 0.06 ? 3 : ratio < 0.08 ? 4 : 5;
export function useBoundaries() {
  return useQuery({
    queryKey: ["boundaries"],
    queryFn: async ({ signal }) => {
      const r = await fetch("/ntpc-districts.geojson", { signal });
      if (!r.ok) throw Error("Boundary unavailable");
      const data = (await r.json()) as FeatureCollection;
      if (data.type !== "FeatureCollection" || data.features.length !== 29)
        throw Error("Invalid boundaries");
      return data;
    },
    staleTime: Infinity,
    retry: false,
  });
}
const project = ([lon, lat]: Position) => [
  (lon - 121.27) * 770 + 15,
  (25.31 - lat) * 890 + 15,
];
function polygons(g: Geometry): Position[][][] {
  return g.type === "MultiPolygon"
    ? g.coordinates
    : g.type === "Polygon"
      ? [g.coordinates]
      : [];
}
export function Choropleth({
  districts,
  selected,
  onSelect,
  onActivate,
}: {
  districts: District[];
  selected?: string;
  onSelect: (town: string) => void;
  onActivate?: (town: string) => void;
}) {
  const boundaries = useBoundaries();
  const navigate = useNavigate();
  return (
    <QueryState query={boundaries}>
      {(data) => (
        <>
          <svg
            className={s.districtSvg}
            viewBox="0 0 600 600"
            aria-label="新北市各行政區高風險園所比例"
          >
            <title>新北市 29 區高風險園所比例</title>
            {data.features.map((f) => {
              const town = String(f.properties?.town);
              const d = districts.find((x) => x.town === town);
              const rings = polygons(f.geometry);
              const coords = rings.flat(2).map(project);
              const center = coords.reduce(
                (a, p) => [
                  a[0] + p[0] / coords.length,
                  a[1] + p[1] / coords.length,
                ],
                [0, 0],
              );
              return (
                <g key={town}>
                  <path
                    className={`${s.districtShape} ${selected === town ? s.highlight : ""}`}
                    d={rings
                      .map((p) =>
                        p
                          .map(
                            (r) =>
                              r
                                .map(
                                  (pos, i) =>
                                    `${i ? "L" : "M"}${project(pos).join(",")}`,
                                )
                                .join(" ") + "Z",
                          )
                          .join(" "),
                      )
                      .join(" ")}
                    fill={`var(--c-heat-${heatLevel(d?.high_risk_ratio ?? 0)})`}
                    fillRule="evenodd"
                    tabIndex={0}
                    role={onActivate ? "button" : "link"}
                    aria-label={`${town}，高風險比例 ${percent(d?.high_risk_ratio ?? 0)}，查看園所`}
                    onMouseEnter={() => onSelect(town)}
                    onFocus={() => onSelect(town)}
                    onClick={() =>
                      onActivate
                        ? onActivate(town)
                        : navigate(`/?town=${encodeURIComponent(town)}`)
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || (onActivate && e.key === " ")) {
                        e.preventDefault();
                        if (onActivate) onActivate(town);
                        else navigate(`/?town=${encodeURIComponent(town)}`);
                      }
                    }}
                  >
                    <title>
                      {town} · 園數 {d?.park_count ?? "未提供"} · 高風險{" "}
                      {d?.high_risk_count ?? "未提供"} · 比例{" "}
                      {percent(d?.high_risk_ratio ?? 0)} · 輿情{" "}
                      {d?.media_heat ?? "未提供"}
                    </title>
                  </path>
                  <text x={center[0]} y={center[1]} textAnchor="middle">
                    {town}
                  </text>
                </g>
              );
            })}
          </svg>
          <div className={s.legend}>
            {["0–2%", "2–4%", "4–6%", "6–8%", "8% 以上"].map((label, i) => (
              <span key={label}>
                <i
                  className={s.swatch}
                  style={{ background: `var(--c-heat-${i + 1})` }}
                />
                {label}
              </span>
            ))}
          </div>
          <p>顏色代表該區高風險園所占比例，非絕對數量。</p>
          <small>
            邊界：
            <a
              href="https://github.com/ronnywang/twgeojson"
              target="_blank"
              rel="noreferrer"
            >
              twgeojson（2011）
            </a>
            ，僅供分布示意，非地籍界線。
          </small>
        </>
      )}
    </QueryState>
  );
}
