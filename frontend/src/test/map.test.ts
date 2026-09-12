import { describe, it, expect, vi, beforeEach } from "vitest";
import { loadMapParks, filterMapParks } from "../api/map";
import { request } from "../api/client";
import type { MapData } from "../api/types";

vi.mock("../api/client", () => ({ request: vi.fn() }));
const data: MapData = {
  type: "FeatureCollection",
  features: ["公立", "非營利", "私立"].map((type, index) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [121.5, 25] },
    properties: {
      park_id: String(index),
      name: `測試園${index}`,
      town: index === 2 ? "新店區" : "板橋區",
      tier: index === 1 ? "低" : "高",
      risk_score: 50,
      pun_count: 0,
      has_abuse: false,
      institution_type: type as "公立" | "私立" | "非營利",
    },
  })),
};
beforeEach(() => vi.mocked(request).mockReset());
describe("map filters and legacy API compatibility", () => {
  it("combines multiple institution types with town, risk and keyword filters", () => {
    expect(filterMapParks(data, new URLSearchParams()).features).toHaveLength(
      3,
    );
    const selected = filterMapParks(
      data,
      new URLSearchParams("type=公立&type=非營利&town=板橋區&tier=低&q=測試"),
    );
    expect(selected.features.map((f) => f.properties.park_id)).toEqual(["1"]);
    expect(
      filterMapParks(data, new URLSearchParams("q=不存在")).features,
    ).toHaveLength(0);
  });
  it("joins a legacy map to all index pages by ID without guessing from names", async () => {
    const legacy = {
      ...data,
      features: data.features.map((f) => ({
        ...f,
        properties: {
          ...f.properties,
          institution_type: undefined,
          town: undefined,
        },
      })),
    };
    vi.mocked(request)
      .mockResolvedValueOnce(legacy)
      .mockResolvedValueOnce({
        total: 3,
        size: 2,
        page: 1,
        items: [
          { park_id: "1", institution_type: "非營利", town: "板橋區" },
          { park_id: "0", institution_type: "公立", town: "板橋區" },
        ],
      })
      .mockResolvedValueOnce({
        total: 3,
        size: 2,
        page: 2,
        items: [{ park_id: "2", institution_type: "私立", town: "新店區" }],
      });
    const result = await loadMapParks();
    expect(result.features.map((f) => f.properties.institution_type)).toEqual([
      "公立",
      "非營利",
      "私立",
    ]);
    expect(result.features[2].properties.town).toBe("新店區");
    expect(request).toHaveBeenLastCalledWith(
      "/parks?size=200&page=2",
      expect.anything(),
      undefined,
    );
  });
  it("uses institution types supplied by the map API without fetching the index", async () => {
    vi.mocked(request).mockResolvedValueOnce(data);
    expect(await loadMapParks()).toEqual(data);
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("surfaces an index failure instead of silently showing incorrect filtered results", async () => {
    vi.mocked(request)
      .mockResolvedValueOnce({
        ...data,
        features: [
          {
            ...data.features[0],
            properties: {
              ...data.features[0].properties,
              institution_type: undefined,
            },
          },
        ],
      })
      .mockRejectedValueOnce(new Error("offline"));
    await expect(loadMapParks()).rejects.toThrow("offline");
  });
});
