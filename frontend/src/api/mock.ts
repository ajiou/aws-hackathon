import { ApiError, fetchJson } from "./client";
import { parkSchema, worklistSchema } from "./types";
import { z } from "zod";
const cache = new Map<string, unknown>();
async function file(name: string, signal?: AbortSignal) {
  if (!cache.has(name)) {
    const result = (await fetchJson(`/${name}.json`, signal, "/mock")) as {
      body: unknown;
    };
    cache.set(name, result.body);
  }
  return cache.get(name);
}
export async function mockRequest(
  path: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const url = new URL(path, "http://mock");
  const q = url.searchParams;
  if (["/meta", "/districts", "/curve"].includes(url.pathname))
    return file(url.pathname.slice(1), signal);
  const scores = z
    .object({ items: z.array(parkSchema) })
    .parse(await file("scores", signal)).items;
  if (url.pathname.startsWith("/parks/")) {
    const id = decodeURIComponent(url.pathname.split("/")[2]);
    const park = scores.find((p) => p.park_id === id);
    if (!park) throw new ApiError(404, "mock", "查無此園所");
    if (url.pathname.endsWith("/brief")) {
      const briefs = (await file("briefs", signal)) as Record<string, unknown>;
      return briefs[id];
    }
    return park;
  }
  let items = scores.filter(
    (p) => p.is_active || q.get("include_inactive") === "true",
  );
  for (const [key, get] of [
    ["town", (p: (typeof items)[number]) => p.town],
    ["type", (p: (typeof items)[number]) => p.institution_type],
    ["tier", (p: (typeof items)[number]) => p.risk.tier],
  ] as const) {
    const selected = q.getAll(key);
    if (selected.length)
      items = items.filter((p) => selected.includes(get(p) ?? ""));
  }
  const search = q.get("q")?.trim();
  if (search) items = items.filter((p) => p.name.includes(search));
  if (q.get("has_finance_flag") === "true")
    items = items.filter((p) => p.finance_flags.length);
  const sort = q.get("sort") ?? "risk";
  const dir =
    q.get("dir") ?? (sort === "risk" || sort === "pun_count" ? "desc" : "asc");
  items.sort((a, b) => {
    const comparison =
      sort === "name"
        ? a.name.localeCompare(b.name, "zh-Hant")
        : sort === "pun_count"
          ? a.timeline.length - b.timeline.length
          : sort === "rank"
            ? (a.risk.rank ?? Infinity) - (b.risk.rank ?? Infinity)
            : (b.risk.rank ?? Infinity) - (a.risk.rank ?? Infinity);
    return (
      (dir === "desc" ? -comparison : comparison) ||
      a.park_id.localeCompare(b.park_id)
    );
  });
  const k = Math.min(200, Math.max(1, Number(q.get("k")) || 50));
  if (url.pathname === "/risk/top")
    return {
      k,
      items: items
        .sort((a, b) => (a.risk.rank ?? Infinity) - (b.risk.rank ?? Infinity))
        .slice(0, k),
    };
  if (url.pathname === "/parks") {
    const page = Math.max(1, Number(q.get("page")) || 1),
      size = Math.min(200, Math.max(1, Number(q.get("size")) || 50));
    return {
      total: items.length,
      page,
      size,
      items: items
        .slice((page - 1) * size, page * size)
        .map((p) => ({
          ...p,
          pun_count: p.timeline.length,
          has_finance_flag: !!p.finance_flags.length,
          has_media_signal: p.media.has_signal,
        })),
    };
  }
  if (url.pathname === "/map")
    return {
      type: "FeatureCollection",
      features: items
        .filter((p) => p.lon !== null && p.lat !== null)
        .map((p) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [p.lon, p.lat] },
          properties: {
            park_id: p.park_id,
            name: p.name,
            town: p.town,
            tier: p.risk.tier,
            risk_score: p.risk.score,
            pun_count: p.timeline.length,
            has_abuse: p.timeline.some((t) => t.category === "不當管教"),
          },
        })),
    };
  if (url.pathname === "/worklist") {
    const work = worklistSchema.parse(await file("worklist", signal));
    // The fixture contains 50 authored work items. Never fabricate inspection advice.
    return {
      ...work,
      week: q.get("week") ?? work.week,
      items: work.items.slice(0, k),
    };
  }
  throw new ApiError(404, "mock", "查無此資源");
}
