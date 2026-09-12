import type {
  ExpressionSpecification,
  StyleSpecification,
  SymbolLayerSpecification,
} from "maplibre-gl";

// OpenFreeMap serves the OpenMapTiles schema. Keeping the style local lets us
// select orientation landmarks without enabling every shop/restaurant label.
const localName: ExpressionSpecification = [
  "coalesce",
  ["get", "name:zh-Hant"],
  ["get", "name:zh"],
  ["get", "name"],
  "",
];
const labelLayout: SymbolLayerSpecification["layout"] = {
  "text-field": localName,
  "text-font": ["sans-serif"],
  "text-size": 12,
  "text-max-width": 8,
  "text-padding": 12,
  "text-allow-overlap": false,
};
const labelPaint: SymbolLayerSpecification["paint"] = {
  "text-color": "#526477",
  "text-halo-color": "#ffffff",
  "text-halo-width": 1.5,
};

export function createMapStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      openmaptiles: {
        type: "vector",
        url: "https://tiles.openfreemap.org/planet",
        attribution:
          '<a href="https://openfreemap.org/" target="_blank" rel="noreferrer">OpenFreeMap</a> © <a href="https://openmaptiles.org/" target="_blank" rel="noreferrer">OpenMapTiles</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>',
      },
      districts: {
        type: "geojson",
        data: "/ntpc-districts.geojson",
        attribution:
          '<a href="https://github.com/ronnywang/twgeojson" target="_blank" rel="noreferrer">行政區界：twgeojson（2011，分布示意）</a>',
      },
    },
    layers: [
      {
        id: "background",
        type: "background",
        paint: { "background-color": "#f4f5f2" },
      },
      {
        id: "landcover",
        type: "fill",
        source: "openmaptiles",
        "source-layer": "landcover",
        filter: ["match", ["get", "class"], ["wood", "grass"], true, false],
        paint: { "fill-color": "#e5eddf", "fill-opacity": 0.65 },
      },
      {
        id: "parks",
        type: "fill",
        source: "openmaptiles",
        "source-layer": "park",
        paint: { "fill-color": "#dce9d5", "fill-opacity": 0.65 },
      },
      {
        id: "water",
        type: "fill",
        source: "openmaptiles",
        "source-layer": "water",
        paint: { "fill-color": "#dceaf0" },
      },
      {
        id: "waterways",
        type: "line",
        source: "openmaptiles",
        "source-layer": "waterway",
        minzoom: 10,
        paint: {
          "line-color": "#cbdfe9",
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.5, 16, 3],
        },
      },
      {
        id: "minor-roads",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        minzoom: 13,
        filter: ["match", ["get", "class"], ["minor", "service"], true, false],
        paint: {
          "line-color": "#ffffff",
          "line-width": ["interpolate", ["linear"], ["zoom"], 13, 1, 17, 5],
        },
      },
      {
        id: "main-road-casing",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: [
          "match",
          ["get", "class"],
          ["motorway", "trunk", "primary", "secondary", "tertiary"],
          true,
          false,
        ],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#ccd0c8",
          "line-width": [
            "interpolate",
            ["linear"],
            ["zoom"],
            8,
            0.8,
            12,
            2.8,
            16,
            8,
          ],
        },
      },
      {
        id: "main-roads",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: [
          "match",
          ["get", "class"],
          ["motorway", "trunk", "primary", "secondary", "tertiary"],
          true,
          false,
        ],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": [
            "match",
            ["get", "class"],
            ["motorway", "trunk"],
            "#eadcbd",
            "#ffffff",
          ],
          "line-width": [
            "interpolate",
            ["linear"],
            ["zoom"],
            8,
            0.4,
            12,
            1.8,
            16,
            6,
          ],
        },
      },
      {
        id: "railways",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        minzoom: 11,
        filter: ["match", ["get", "class"], ["rail", "transit"], true, false],
        paint: {
          "line-color": "#9babb6",
          "line-width": 1,
          "line-dasharray": [3, 3],
        },
      },
      {
        id: "district-outline",
        type: "line",
        source: "districts",
        paint: {
          "line-color": "#899cab",
          "line-width": 1.2,
          "line-opacity": 0.7,
          "line-dasharray": [4, 3],
        },
      },
      {
        id: "main-road-names",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "transportation_name",
        minzoom: 13,
        filter: [
          "match",
          ["get", "class"],
          ["motorway", "trunk", "primary", "secondary"],
          true,
          false,
        ],
        layout: {
          ...labelLayout,
          "symbol-placement": "line",
          "symbol-spacing": 350,
          "text-size": 11,
        },
        paint: labelPaint,
      },
      {
        id: "park-names",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "park",
        minzoom: 12,
        layout: { ...labelLayout, "text-padding": 24 },
        paint: { ...labelPaint, "text-color": "#526d50" },
      },
      {
        id: "major-landmarks",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "poi",
        minzoom: 11,
        filter: [
          "all",
          [
            "any",
            [
              "match",
              ["get", "class"],
              ["railway", "rail", "park"],
              true,
              false,
            ],
            [
              "match",
              ["get", "subclass"],
              ["hospital", "museum", "park", "town_hall"],
              true,
              false,
            ],
          ],
          ["<=", ["coalesce", ["get", "rank"], 999], 3],
        ],
        layout: {
          ...labelLayout,
          "symbol-sort-key": ["get", "rank"],
          "text-padding": 24,
          "text-variable-anchor": ["top", "bottom", "left", "right"],
          "text-radial-offset": 0.6,
        },
        paint: labelPaint,
      },
      {
        id: "airports",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "aerodrome_label",
        minzoom: 10,
        filter: ["has", "iata"],
        layout: labelLayout,
        paint: labelPaint,
      },
      {
        id: "city-names",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "place",
        minzoom: 7,
        maxzoom: 12,
        filter: ["==", ["get", "class"], "city"],
        layout: { ...labelLayout, "text-size": 15, "text-padding": 24 },
        paint: { ...labelPaint, "text-color": "#475569" },
      },
      // MapLibre places point labels inside polygons, so all 29 names come from
      // the same local boundary data and remain available if tile requests fail.
      {
        id: "district-names",
        type: "symbol",
        source: "districts",
        minzoom: 8,
        layout: {
          ...labelLayout,
          "text-field": ["get", "town"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 8, 12, 13, 16],
          "text-padding": 5,
          "text-variable-anchor": ["bottom", "top", "left", "right"],
          "text-radial-offset": 1.6,
        },
        paint: { ...labelPaint, "text-color": "#45576a", "text-halo-width": 2 },
      },
    ],
  };
}
