import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import {
  parkSchema,
  parksSchema,
  topSchema,
  mapSchema,
  metaSchema,
  districtsSchema,
  curveSchema,
  worklistSchema,
} from "../api/types";
const read = (name: string) =>
  JSON.parse(readFileSync(`mock/${name}.json`, "utf8"));
describe("frozen API contracts", () => {
  it("validates every supplied response and every park, strips owner fields", () => {
    for (const [name, schema] of [
      ["meta", metaSchema],
      ["parks", parksSchema],
      ["risk-top", topSchema],
      ["map", mapSchema],
      ["districts", districtsSchema],
      ["curve", curveSchema],
      ["worklist", worklistSchema],
    ] as const)
      expect(schema.safeParse(read(name)).success, name).toBe(true);
    for (const p of read("scores").items) {
      const clean = parkSchema.parse(p);
      expect(clean).not.toHaveProperty("owner_key");
      expect(clean.reasons.length).toBeLessThanOrEqual(3);
    }
  });
  it("rejects missing reasons and numeric scores for inapplicable dimensions", () => {
    const park = read("scores").items[0];
    expect(parkSchema.safeParse({ ...park, reasons: undefined }).success).toBe(
      false,
    );
    expect(
      parkSchema.safeParse({
        ...park,
        dimensions: {
          ...park.dimensions,
          operation: {
            ...park.dimensions.operation,
            applicable: false,
            score: 0,
          },
        },
      }).success,
    ).toBe(false);
  });
  it("accepts documented nested fees and finance with presigned links", () => {
    const park = read("scores").items[0];
    const result = parkSchema.parse({
      ...park,
      fees: {
        school_year: 115,
        items: [
          {
            age: 5,
            item: "學費",
            period: "學期",
            term1_full: 7000,
            term2_full: 7000,
            term1_half: 4500,
            term2_half: 4500,
          },
        ],
      },
      finance: [
        {
          school_year: 113,
          metrics: { personnel_budget: 5000 },
          validated: false,
          presigned_url: "https://example.org/report.pdf",
        },
      ],
    });
    expect(result.fees).toHaveLength(4);
    expect(result.finance?.[0].pdf_url).toBe("https://example.org/report.pdf");
  });
});

// 輿情維度一律不計分（ADR-0001），但「為什麼不計分」對兩種園是不同的事實：
// 有園級訊號的 14 園是樣本太小無從驗證，其餘是區級熱度實測無鑑別力。
// 對有訊號的園寫「區級熱度無鑑別力」，等於否認它自己頁面上那幾篇明文點名的
// 報導——稽查人員看到會直接不信這張表。這裡兩邊都釘住。
describe("sentiment dimension explains itself correctly", () => {
  const items = read("scores").items as Array<{
    media: { has_signal: boolean };
    dimensions: { sentiment: { weight: number | null; note: string | null } };
  }>;
  it("never scores the dimension and never mixes up the two reasons", () => {
    const signalled = items.filter((p) => p.media.has_signal);
    expect(signalled.length).toBeGreaterThan(0);
    expect(signalled.length).toBeLessThan(items.length);
    for (const park of items) {
      const { weight, note } = park.dimensions.sentiment;
      expect(weight).toBeNull();
      expect(note).toBeTruthy();
      if (park.media.has_signal) {
        expect(note).toContain("樣本太小");
        expect(note).not.toContain("區級熱度實測無鑑別力");
      } else {
        expect(note).toContain("區級熱度實測無鑑別力");
      }
    }
  });
});
