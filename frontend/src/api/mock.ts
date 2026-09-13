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
  // 有無裁罰紀錄。省略＝不篩，true / false 兩邊都要篩得出來。
  const punished = q.get("punished");
  if (punished === "true" || punished === "false")
    items = items.filter(
      (p) => p.timeline.length > 0 === (punished === "true"),
    );
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
      items: items.slice((page - 1) * size, page * size).map((p) => ({
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
            institution_type: p.institution_type,
            tier: p.risk.tier,
            risk_score: p.risk.score,
            pun_count: p.timeline.length,
            has_abuse: p.timeline.some((t) => t.category === "不當管教"),
          },
        })),
    };
  // 示範資料的 media_coverage 就掛在 scores 上，聚合規則與後端 /media 相同，
  // 兩邊算出來的名次才會一致。
  if (url.pathname === "/media") {
    const months = Math.min(120, Math.max(1, Number(q.get("months")) || 12));
    const rows = scores.flatMap((p) =>
      (p.media_coverage ?? []).map((c) => ({ park: p, c })),
    );
    if (!rows.length) return { months, as_of: "", since: "", items: [] };
    const as_of = rows.reduce((a, r) => (r.c.date > a ? r.c.date : a), "");
    const since = new Date(
      new Date(as_of).getTime() - months * 30 * 86_400_000,
    )
      .toISOString()
      .slice(0, 10);
    const grouped = new Map<string, typeof rows>();
    for (const row of rows.filter((r) => r.c.date >= since)) {
      const bucket = grouped.get(row.park.park_id) ?? [];
      bucket.push(row);
      grouped.set(row.park.park_id, bucket);
    }
    return {
      months,
      as_of,
      since,
      items: [...grouped.values()]
        .map((group) => {
          const park = group[0].park;
          const kinds = new Map<string, number>();
          for (const { c } of group)
            if (c.event_type)
              kinds.set(c.event_type, (kinds.get(c.event_type) ?? 0) + 1);
          const severities = group
            .map(({ c }) => c.severity)
            .filter((v): v is number => typeof v === "number");
          return {
            park_id: park.park_id,
            name: park.name,
            town: park.town,
            tier: park.risk.tier,
            sri: park.media.sri,
            article_count: group.length,
            latest_date: group.reduce(
              (a, r) => (r.c.date > a ? r.c.date : a),
              "",
            ),
            max_severity: severities.length ? Math.max(...severities) : null,
            top_event_type:
              [...kinds.entries()].sort(
                (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
              )[0]?.[0] ?? null,
            after_cutoff_count: group.filter(({ c }) => c.is_after_cutoff)
              .length,
          };
        })
        .sort(
          (a, b) =>
            b.article_count - a.article_count ||
            a.latest_date.localeCompare(b.latest_date) ||
            a.park_id.localeCompare(b.park_id),
        ),
    };
  }
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
