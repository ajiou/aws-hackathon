import { useEffect, useRef, useState } from "react";
import {
  Map,
  NavigationControl,
  setWorkerUrl,
  type GeoJSONSource,
  type ExpressionSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { District, MapData } from "../api/types";
import { createMapStyle } from "./mapStyle";
import { heatLevel } from "./Choropleth";
import s from "../styles/App.module.css";
// MapLibre 6 workers live in a separate module; Vite must emit its URL explicitly.
setWorkerUrl(workerUrl);
const cssVar = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();
// MapLibre 自己解析 paint 值，看不懂 CSS 的 var()，所以色票要先解析成 hex 再組表達式。
function heatFill(districts: District[]): ExpressionSpecification | string {
  const base = cssVar("--c-heat-1");
  const pairs = districts.flatMap((d) => [
    d.town,
    cssVar(`--c-heat-${heatLevel(d.high_risk_ratio)}`),
  ]);
  return pairs.length
    ? ([
        "match",
        ["get", "town"],
        ...pairs,
        base,
      ] as unknown as ExpressionSpecification)
    : base;
}
export default function MapCanvas({
  data,
  districts,
  mode,
  selectedTown,
  onSelect,
  onSelectTown,
}: {
  data: MapData;
  districts: District[];
  mode: "points" | "districts";
  selectedTown?: string;
  onSelect: (id: string) => void;
  onSelectTown: (town: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null),
    instance = useRef<Map>(),
    select = useRef(onSelect),
    selectTown = useRef(onSelectTown),
    heat = useRef(districts),
    town = useRef(selectedTown);
  const [failed, setFailed] = useState(false);
  const [tileError, setTileError] = useState(false);
  const [rendering, setRendering] = useState(true);
  const printImage = useRef<HTMLImageElement>(null);
  select.current = onSelect;
  selectTown.current = onSelectTown;
  heat.current = districts;
  town.current = selectedTown;
  useEffect(() => {
    const capture = () => {
      try {
        if (printImage.current && instance.current)
          printImage.current.src = instance.current
            .getCanvas()
            .toDataURL("image/png");
      } catch {
        /* Text summary remains printable if the browser blocks canvas export. */
      }
    };
    window.addEventListener("beforeprint", capture);
    return () => window.removeEventListener("beforeprint", capture);
  }, []);
  useEffect(() => {
    if (!host.current) return;
    let map: Map;
    try {
      map = new Map({
        container: host.current,
        style: createMapStyle(),
        bounds: [
          [121.27, 24.67],
          [122.01, 25.3],
        ],
        fitBoundsOptions: {
          padding: { top: 100, bottom: 45, left: 30, right: 30 },
        },
        canvasContextAttributes: { preserveDrawingBuffer: true },
      });
      instance.current = map;
      map.addControl(new NavigationControl(), "top-left");
    } catch {
      setFailed(true);
      return;
    }
    map.on("error", () => setTileError(true));
    map.on("sourcedataloading", () => setRendering(true));
    map.on("idle", () => setRendering(false));
    map.on("style.load", () => {
      const color = cssVar;
      const institutionColor: ExpressionSpecification = [
        "match",
        ["coalesce", ["get", "institution_type"], ["get", "type"]],
        "公立",
        "#2563eb",
        "非營利",
        "#0d9488",
        "私立",
        "#7c3aed",
        "#64748b",
      ];
      // 熱力層墊在行政區界線底下，園所點位才不會被蓋住、也不會被吃掉點擊。
      map.addLayer(
        {
          id: "district-heat",
          type: "fill",
          source: "districts",
          layout: { visibility: mode === "districts" ? "visible" : "none" },
          paint: {
            "fill-color": heatFill(heat.current),
            "fill-opacity": 0.72,
          },
        },
        "district-outline",
      );
      map.addLayer(
        {
          id: "district-heat-selected",
          type: "line",
          source: "districts",
          layout: { visibility: mode === "districts" ? "visible" : "none" },
          filter: ["==", ["get", "town"], town.current ?? ""],
          paint: {
            "line-color": color("--c-primary") || "#1d4ed8",
            "line-width": 3,
          },
        },
        "district-names",
      );
      map.on("click", "district-heat", (e) => {
        const name = e.features?.[0]?.properties?.town;
        if (name) selectTown.current(String(name));
      });
      performance.mark("watchdog-points-start");
      const measured = () => {
        if (map.getSource("parks") && map.isSourceLoaded("parks")) {
          map.off("sourcedata", measured);
          map.once("render", () => {
            performance.mark("watchdog-points-end");
            performance.measure(
              "watchdog-points",
              "watchdog-points-start",
              "watchdog-points-end",
            );
          });
        }
      };
      map.on("sourcedata", measured);
      map.addSource("parks", {
        type: "geojson",
        data,
        cluster: true,
        clusterMaxZoom: 12,
        clusterRadius: 45,
      });
      const pointsVisible = mode === "points" ? "visible" : "none";
      map.addLayer({
        id: "clusters",
        type: "circle",
        source: "parks",
        filter: ["has", "point_count"],
        layout: { visibility: pointsVisible },
        paint: {
          "circle-radius": [
            "step",
            ["get", "point_count"],
            18,
            20,
            23,
            100,
            29,
          ],
          "circle-color": "#334d66",
          "circle-stroke-width": 3,
          "circle-stroke-color": color("--c-bg"),
        },
      });
      map.addLayer({
        id: "counts",
        type: "symbol",
        source: "parks",
        filter: ["has", "point_count"],
        layout: {
          visibility: pointsVisible,
          "text-field": ["get", "point_count_abbreviated"],
          "text-font": ["sans-serif"],
          "text-size": 12,
        },
        paint: { "text-color": color("--c-bg") },
      });
      map.addLayer({
        id: "points",
        type: "circle",
        source: "parks",
        filter: ["!", ["has", "point_count"]],
        layout: { visibility: pointsVisible },
        paint: {
          "circle-radius": 7,
          "circle-color": institutionColor,
          "circle-stroke-width": 2,
          "circle-stroke-color": color("--c-bg"),
        },
      });
      map.on("click", "points", (e) => {
        const id = e.features?.[0].properties?.park_id;
        if (id) select.current(String(id));
      });
      map.on("click", "clusters", async (e) => {
        const f = e.features?.[0];
        if (!f || f.geometry.type !== "Point") return;
        try {
          const zoom = await (
            map.getSource("parks") as GeoJSONSource
          ).getClusterExpansionZoom(Number(f.properties?.cluster_id));
          map.easeTo({
            center: f.geometry.coordinates as [number, number],
            zoom,
          });
        } catch {
          // The source can change while filters update or the map unmounts.
        }
      });
      for (const layer of ["clusters", "points", "district-heat"]) {
        map.on("mouseenter", layer, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layer, () => {
          map.getCanvas().style.cursor = "";
        });
      }
    });
    return () => {
      map.remove();
      instance.current = undefined;
    };
  }, []);
  useEffect(() => {
    const map = instance.current;
    if (!map) return;
    const update = () => {
      (map.getSource("parks") as GeoJSONSource | undefined)?.setData(data);
    };
    if (map.getSource("parks")) update();
    else map.once("style.load", update);
    return () => {
      map.off("style.load", update);
    };
  }, [data]);
  // 圖層切換、熱力配色、選取框都可能在 style 載入完成前被觸發，所以一律走
  // 「現在有圖層就直接套，沒有就等 style.load」這個模式。
  useEffect(() => {
    const map = instance.current;
    if (!map) return;
    const update = () => {
      const districtMode = mode === "districts";
      const visibility: [string, boolean][] = [
        ["district-heat", districtMode],
        ["district-heat-selected", districtMode],
        ["clusters", !districtMode],
        ["counts", !districtMode],
        ["points", !districtMode],
      ];
      for (const [id, on] of visibility)
        if (map.getLayer(id))
          map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    };
    if (map.getLayer("district-heat")) update();
    else map.once("style.load", update);
    return () => {
      map.off("style.load", update);
    };
  }, [mode]);
  useEffect(() => {
    const map = instance.current;
    if (!map) return;
    const update = () => {
      if (map.getLayer("district-heat"))
        map.setPaintProperty(
          "district-heat",
          "fill-color",
          heatFill(districts),
        );
    };
    if (map.getLayer("district-heat")) update();
    else map.once("style.load", update);
    return () => {
      map.off("style.load", update);
    };
  }, [districts]);
  useEffect(() => {
    const map = instance.current;
    if (!map) return;
    const update = () => {
      if (map.getLayer("district-heat-selected"))
        map.setFilter("district-heat-selected", [
          "==",
          ["get", "town"],
          selectedTown ?? "",
        ]);
    };
    if (map.getLayer("district-heat-selected")) update();
    else map.once("style.load", update);
    return () => {
      map.off("style.load", update);
    };
  }, [selectedTown]);
  return (
    <>
      {failed ? (
        <p role="alert" className={s.note}>
          此裝置無法啟用 WebGL 地圖，請使用下方園所選單或右側風險總覽。
        </p>
      ) : (
        <div
          ref={host}
          className={s.map}
          data-map-canvas
          aria-busy={rendering}
          aria-label="園所風險地圖"
        />
      )}
      <img
        ref={printImage}
        className="print-only"
        alt="園所風險地圖列印快照"
        style={{ width: "100%" }}
      />
      {tileError && (
        <p role="status">部分道路或行政區載入失敗；園所資料仍可檢視。</p>
      )}
      <span className="pointer-events-none absolute bottom-10 left-3 rounded-md bg-white/90 px-2 py-1 text-xs text-muted-foreground">
        道路與行政區 · 放大顯示主要地標
      </span>
    </>
  );
}
