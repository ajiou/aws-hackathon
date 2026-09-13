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

// 輿情維度一律不計分（ADR-0001），但「為什麼」對三種園是三件不同的事實。
// 只寫一句，另外兩種就會在自己的頁面上讀到假話。最嚴重的是第二種：報導全在
// 切點之後那 22 園，2026 年的虐童案都在這裡，說成「本園無明文點名的報導」
// 是直接說謊——它們的頁面下方就列著十幾則。
describe("sentiment dimension explains itself correctly", () => {
  const items = read("scores").items as Array<{
    media: { has_signal: boolean };
    media_coverage?: Array<{ is_after_cutoff: boolean }>;
    dimensions: { sentiment: { weight: number | null; note: string | null } };
  }>;
  const state = (p: (typeof items)[number]) => {
    if (p.media.has_signal) return "pre-cutoff";
    const coverage = p.media_coverage ?? [];
    return coverage.length ? "post-cutoff-only" : "none";
  };
  it("covers all three states in the fixture", () => {
    const seen = new Set(items.map(state));
    expect([...seen].sort()).toEqual([
      "none",
      "post-cutoff-only",
      "pre-cutoff",
    ]);
  });
  it("never scores the dimension and never tells a park the wrong story", () => {
    for (const park of items) {
      const { weight, note } = park.dimensions.sentiment;
      expect(weight).toBeNull();
      expect(note).toBeTruthy();
      if (state(park) === "pre-cutoff") {
        expect(note).toContain("樣本太小");
      } else if (state(park) === "post-cutoff-only") {
        // 有報導卻被說成沒有，是這三句話裡最傷的一種錯。
        expect(note).not.toContain("本園無明文點名的報導");
        expect(note).toContain("全部落在資料切點");
      } else {
        expect(note).toContain("區級熱度實測無鑑別力");
      }
      // 只有完全沒有報導的園才適用那句區級熱度的說明。
      if (note!.includes("區級熱度實測無鑑別力"))
        expect(park.media_coverage ?? []).toHaveLength(0);
    }
  });
});
