// 拿前端自己的 zod 契約去打「線上」的 API。
//
// 預設不跑（需要網路，不該拖累 npm test）。部署完手動跑：
//   $env:LIVE_API="https://d2p0ksy36o4foe.cloudfront.net/api/v1"; npx vitest run src/test/live.e2e.test.ts
//
// 為什麼要有這支：verify.ps1 只確認九支路由回 200，不看回來的 JSON
// 形狀對不對。實際壞過兩次都是 200 但前端解不開（meta.weights.sentiment
// 是 null、curve 少了 random），模擬資料永遠驗不出來。
import { describe, it, expect } from "vitest";
import {
  metaSchema, parksSchema, topSchema, districtsSchema,
  curveSchema, worklistSchema, mapSchema, parkSchema, briefSchema,
} from "../api/types";

const B = process.env.LIVE_API ?? "";
const get = async (p: string) => {
  const r = await fetch(B + p);
  expect(r.status, p).toBe(200);
  return r.json();
};

describe.skipIf(!B)("live API vs frontend contract", () => {
  it("all nine routes parse", async () => {
    const show = (n: string, r: { success: boolean; error?: unknown }) => {
      if (!r.success) console.log(n, JSON.stringify(r.error, null, 1).slice(0, 700));
      return r.success;
    };
    expect(show("meta", metaSchema.safeParse(await get("/meta")))).toBe(true);
    const parks = parksSchema.parse(await get("/parks?page=1&page_size=50"));
    expect(parks.total).toBe(1178);
    expect(show("/risk/top", topSchema.safeParse(await get("/risk/top")))).toBe(true);
    expect(show("/districts", districtsSchema.safeParse(await get("/districts")))).toBe(true);
    expect(show("/curve", curveSchema.safeParse(await get("/curve")))).toBe(true);
    expect(show("/map", mapSchema.safeParse(await get("/map")))).toBe(true);
    const wl = worklistSchema.parse(await get("/worklist"));
    expect(wl.items).toHaveLength(50);
    const id = parks.items[0].park_id;
    expect(show("detail", parkSchema.safeParse(await get(`/parks/${id}`)))).toBe(true);
    expect(show("brief", briefSchema.safeParse(await get(`/parks/${id}/brief`)))).toBe(true);
  }, 90000);

  it("every one of the 50 worklist rows parses, not just the first", async () => {
    const wl = worklistSchema.parse(await get("/worklist"));
    for (const i of wl.items) {
      expect(i.reasons.length, `${i.seq}`).toBeGreaterThan(0);
      expect(i.actions.length, `${i.seq}`).toBeGreaterThan(0);
    }
  }, 90000);

  it("every active park on page 1 has a score; closed parks are absent", async () => {
    const parks = parksSchema.parse(await get("/parks?page=1&page_size=50"));
    for (const p of parks.items) expect(p.risk.score, p.park_id).not.toBeNull();
  }, 90000);
});
