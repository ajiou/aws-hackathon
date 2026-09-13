import { useQuery } from "@tanstack/react-query";
import { request } from "./client";
import { mapSchema, parksSchema, type MapData } from "./types";

// The current /map endpoint omits institution type. Join by stable ID using
// every /parks page, never infer public/private status from a school's name.
export async function loadMapParks(signal?: AbortSignal): Promise<MapData> {
  const data = await request("/map", mapSchema, signal);
  if (
    data.features.every(
      (f) => f.properties.institution_type || f.properties.type,
    )
  )
    return data;
  const first = await request("/parks?size=200&page=1", parksSchema, signal);
  const rows = [...first.items];
  const pages = Math.ceil(first.total / first.size);
  for (let page = 2; page <= pages; page++) {
    const result = await request(
      `/parks?size=200&page=${page}`,
      parksSchema,
      signal,
    );
    rows.push(...result.items);
  }
  const parks = new Map(rows.map((row) => [row.park_id, row]));
  return {
    ...data,
    features: data.features.map((feature) => {
      const park = parks.get(feature.properties.park_id);
      const kind =
        feature.properties.institution_type ??
        feature.properties.type ??
        park?.institution_type;
      return {
        ...feature,
        properties: {
          ...feature.properties,
          town: feature.properties.town ?? park?.town,
          institution_type:
            kind === "公立" || kind === "私立" || kind === "非營利"
              ? kind
              : undefined,
        },
      };
    }),
  };
}

export function filterMapParks(
  data: MapData,
  params: URLSearchParams,
): MapData {
  const search = params.get("q")?.trim().toLocaleLowerCase() ?? "";
  // 有無裁罰紀錄。地圖是本機篩選，用點位帶的 pun_count；右側列表走
  // /parks?punished=，兩邊查的是同一件事，判斷式要一致（>0 才算有）。
  const punished = params.get("punished");
  return {
    ...data,
    features: data.features.filter(
      ({ properties: p }) =>
        (!search || p.name.toLocaleLowerCase().includes(search)) &&
        (punished === null || (punished === "true") === p.pun_count > 0) &&
        [
          ["town", p.town],
          ["tier", p.tier],
          ["type", p.institution_type ?? p.type],
        ].every(([key, value]) => {
          const selected = params.getAll(key!);
          return !selected.length || (!!value && selected.includes(value));
        }),
    ),
  };
}

export function useMapParks() {
  return useQuery({
    queryKey: ["map-parks-with-type"],
    queryFn: ({ signal }) => loadMapParks(signal),
    staleTime: 300_000,
  });
}
