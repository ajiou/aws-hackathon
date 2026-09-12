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
