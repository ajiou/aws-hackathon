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
import type { MapData } from "../api/types";
import { createMapStyle } from "./mapStyle";
import s from "../styles/App.module.css";
// MapLibre 6 workers live in a separate module; Vite must emit its URL explicitly.
setWorkerUrl(workerUrl);
export default function MapCanvas({
  data,
  onSelect,
}: {
  data: MapData;
  onSelect: (id: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null),
    instance = useRef<Map>(),
    select = useRef(onSelect);
  const [failed, setFailed] = useState(false);
  const [tileError, setTileError] = useState(false);
  const [rendering, setRendering] = useState(true);
  const printImage = useRef<HTMLImageElement>(null);
  select.current = onSelect;
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
      const css = getComputedStyle(document.documentElement),
        color = (name: string) => css.getPropertyValue(name).trim();
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
      map.addLayer({
        id: "clusters",
        type: "circle",
        source: "parks",
        filter: ["has", "point_count"],
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
      for (const layer of ["clusters", "points"]) {
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
  return (
    <>
      {failed ? (
        <p role="alert" className={s.note}>
          此裝置無法啟用 WebGL 地圖，請使用下方園所選單或行政區模式。
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
        <p role="status">部分道路或地標載入失敗；行政區與園所資料仍可檢視。</p>
      )}
      <span className="pointer-events-none absolute bottom-10 left-3 rounded-md bg-white/90 px-2 py-1 text-xs text-muted-foreground">
        道路與行政區 · 放大顯示主要地標
      </span>
    </>
  );
}
