import { z } from "zod";
const score = z.number().min(0).max(100);
const ratio = z.number().min(0).max(1);
export const tierSchema = z.enum(["高", "中", "低"]);
export const dimensionNames = {
  violation: "違規",
  evaluation: "評鑑",
  sentiment: "輿情",
  operation: "營運",
} as const;
const dimensionKey = z.enum([
  "violation",
  "evaluation",
  "sentiment",
  "operation",
]);
export const reasonSchema = z.object({
  code: z.string(),
  label: z.string(),
  weight: z.number(),
  dimension: dimensionKey,
  validated: z.boolean(),
});
export const riskSchema = z.object({
  // 已停辦的 37 園 score / rank / tier 三個都是 null（SPEC §2）。
  // 寫成必填數字會讓詳情頁在這些園所上整頁空白。
  score: score.nullable(),
  rank: z.number().int().nonnegative().nullable(),
  tier: tierSchema.nullable(),
  coverage: ratio.optional(),
  // score 是同儕群內百分位，raw 才是四維度加權的結果，兩者差很多
  // （排名第 1 的園 score=100.0 但 raw=84.0，第 200 名 79.6 對 29.3）。
  // 之前 raw 連 schema 都沒有，會被 zod 直接 strip 掉，畫面上只剩百分位
  // 疊在加權明細上方，讀起來就像加權算錯了。
  raw: z.number().optional(),
  score_basis: z.string().optional(),
  rank_basis: z.string().optional(),
});
const institution = z.enum(["公立", "私立", "非營利"]);
const typeFields = {
  institution_type: institution.optional(),
  type: institution.optional(),
};
const normalizeType = <T extends { institution_type?: string; type?: string }>(
  row: T,
) => ({
  ...row,
  institution_type: row.institution_type ?? row.type ?? "未提供",
});
export const parkRowSchema = z
  .object({
    park_id: z.string(),
    name: z.string(),
    ...typeFields,
    town: z.string(),
    lon: z.number().nullable(),
    lat: z.number().nullable(),
    is_active: z.union([z.literal(0), z.literal(1)]),
    risk: riskSchema,
    pun_count: z.number(),
    has_finance_flag: z.boolean(),
    has_media_signal: z.boolean(),
    reasons: z.array(reasonSchema).optional(),
  })
  .transform(normalizeType);
const dimensionSchema = z
  .object({
    applicable: z.boolean(),
    score: score.nullable(),
    coverage: ratio,
    weight: z.number().nullable(),
    validated: z.boolean(),
    note: z.string().nullish(),
  })
  .refine(
    (d) => d.applicable || d.score === null,
    "不適用的維度不得提供數值分數",
  );
const feeRow = z.object({
  year: z.union([z.string(), z.number()]),
  item: z.string(),
  amount: z.number().nullable(),
  period: z.string().optional(),
});
const feeDocument = z.object({
  school_year: z.number(),
  items: z.array(
    z.object({
      age: z.number(),
      item: z.string(),
      period: z.string(),
      term1_full: z.number().nullable(),
      term2_full: z.number().nullable(),
      term1_half: z.number().nullable(),
      term2_half: z.number().nullable(),
    }),
  ),
});
const feesSchema = z
  .union([z.array(feeRow), feeDocument, z.array(feeDocument)])
  .transform((data) => {
    if (Array.isArray(data) && (!data.length || "year" in data[0]))
      return data as z.infer<typeof feeRow>[];
    const docs = Array.isArray(data)
      ? (data as z.infer<typeof feeDocument>[])
      : [data];
    return docs.flatMap((d) =>
      d.items.flatMap((item) =>
        (["term1_full", "term2_full", "term1_half", "term2_half"] as const).map(
          (key) => ({
            year: d.school_year,
            item: `${item.age} 歲 · ${item.item}`,
            period: `${item.period} · ${{ term1_full: "上學期全日", term2_full: "下學期全日", term1_half: "上學期半日", term2_half: "下學期半日" }[key]}`,
            amount: item[key],
          }),
        ),
      ),
    );
  });
const financeDocument = z
  .object({
    year: z.union([z.string(), z.number()]).nullish(),
    // 公立-附設園沒有自己的學年度——決算併進所屬學校，教育局本身就沒有
    // 「板橋國小附幼」這個預算單位（見 etl/build_curated.assign_peer_groups）。
    // 269 筆這樣的列在來源就是 null，不是資料缺漏。
    school_year: z.number().nullish(),
    title: z.string().nullish(),
    // backend 在沒有 S3 bucket 時（本機、或該園沒有公開 PDF）會明確送
    // pdf_url: null，不是省略欄位。.optional() 不吃 null，會讓這 12 園的
    // 詳情頁整頁變成「資料載入失敗」。
    url: z.string().url().nullish(),
    pdf_url: z.string().url().nullish(),
    presigned_url: z.string().url().nullish(),
    metrics: z.record(z.number().nullable()).optional(),
    audit_floor_applied: z.number().nullable().optional(),
    validated: z.boolean().optional(),
    // 302 筆財報列裡只有 46 筆有 PDF。其餘能顯示的就是這個分數與 metrics，
    // 不是只有一個點不動的連結。
    operation_score: z.number().nullable().optional(),
  })
  // 這裡原本 refine「財報需要年度」，但 269 筆公立-附設列的年度本來就是
  // null，硬要求年度會讓整個 /parks/{id} 回應驗證失敗，詳情頁整頁變成
  // 「資料載入失敗」——為了一個顯示欄位，把裁罰、評鑑、風險分數全部一起
  // 弄不見。沒有年度就是沒有年度，由畫面決定怎麼呈現。
  .transform((d) => ({
    ...d,
    year: d.year ?? d.school_year ?? null,
    pdf_url: d.pdf_url ?? d.presigned_url,
  }));
export const timelineSchema = z.object({
  date: z.string(),
  category: z.string(),
  law: z.string(),
  fine: z.number().nullable(),
  penalty_raw: z.string(),
  is_after_cutoff: z.boolean(),
});
export const parkSchema = z
  .object({
    park_id: z.string(),
    name: z.string(),
    ...typeFields,
    peer_group: z.string(),
    town: z.string(),
    address: z.string(),
    tel: z.string(),
    lon: z.number().nullable(),
    lat: z.number().nullable(),
    is_active: z.union([z.literal(0), z.literal(1)]),
    count_approved: z.number().nullable(),
    established_at: z.string().nullish(),
    risk: riskSchema,
    dimensions: z.object({
      violation: dimensionSchema,
      evaluation: dimensionSchema,
      sentiment: dimensionSchema,
      operation: dimensionSchema,
    }),
    reasons: z.array(reasonSchema).max(3),
    finance_flags: z.array(
      z.object({
        code: z.string(),
        label: z.string(),
        severity: z.number(),
        year: z.number(),
      }),
    ),
    media: z.object({
      sri: z.number(),
      has_signal: z.boolean(),
      town_heat_per_park: z.number(),
      town_heat_rank: z.number().optional(),
      last_negative_at: z.string().nullable(),
      article_count: z.number().optional(),
      event_count: z.number().optional(),
    }),
    // 展示用輿情明細，**刻意含切點之後的報導**（見 backend MediaCoverage）。
    media_coverage: z
      .array(
        z.object({
          date: z.string(),
          outlet: z.string().nullish(),
          title: z.string(),
          url: z.string().nullish(),
          event_type: z.string().nullish(),
          severity: z.number().nullish(),
          is_after_cutoff: z.boolean(),
        }),
      )
      .optional(),
    timeline: z.array(timelineSchema),
    has_fee: z.boolean().optional(),
    evaluations: z
      .array(
        z.object({
          year: z.union([z.string(), z.number()]),
          result: z.string(),
          kind: z.string().optional(),
          // 完成日。同一學年度可以有基礎評鑑→追蹤評鑑→連續數次行政處分，
          // 沒有日期就看不出這是一條升級鏈。
          date: z.string().nullish(),
        }),
      )
      .optional(),
    fees: feesSchema.nullish(),
    finance: z
      .union([z.array(financeDocument), financeDocument.transform((d) => [d])])
      .nullish(),
  })
  .transform(normalizeType);
const modelSchema = z.object({
  name: z.string(),
  precision_at_50: ratio,
  baseline: ratio,
  lift: z.number().optional(),
});
export const metaSchema = z.object({
  version: z.string(),
  generated_at: z.string(),
  cutoff: z.string(),
  population: z.number(),
  weights: z.record(z.record(z.number().nullable())),
  peer_groups: z.record(
    z.object({ n: z.number(), operation: z.string().nullable().optional() }),
  ),
  score_basis: z.string(),
  rank_basis: z.string(),
  data_freshness: z.record(z.string()),
  model: modelSchema,
});
export const parksSchema = z.object({
  total: z.number(),
  page: z.number(),
  size: z.number(),
  items: z.array(parkRowSchema),
});
export const topSchema = z.object({
  k: z.number(),
  items: z.array(parkSchema),
});
export const districtsSchema = z.object({
  items: z.array(
    z.object({
      town: z.string(),
      park_count: z.number(),
      high_risk_count: z.number(),
      high_risk_ratio: ratio,
      media_heat: z.number(),
      media_heat_per_park: z.number(),
      pun_count_before_cutoff: z.number(),
    }),
  ),
});
export const mapSchema = z.object({
  type: z.literal("FeatureCollection"),
  features: z.array(
    z.object({
      type: z.literal("Feature"),
      geometry: z.object({
        type: z.literal("Point"),
        coordinates: z.tuple([z.number(), z.number()]),
      }),
      properties: z.object({
        park_id: z.string(),
        name: z.string(),
        tier: tierSchema,
        risk_score: score,
        pun_count: z.number(),
        has_abuse: z.boolean(),
        town: z.string().optional(),
      }),
    }),
  ),
});
const stratifiedSchema = z.object({
  n: z.number(),
  baseline: ratio,
  p_at_10: ratio.optional(),
  p_at_20: ratio.optional(),
  p_at_50: ratio.optional(),
  lift_10: z.number().optional(),
  lift_20: z.number().optional(),
  lift_50: z.number().optional(),
});
export const curveSchema = z.object({
  population: z.number(),
  positives: z.number(),
  baseline: ratio,
  points: z.array(
    z.object({
      k: z.number(),
      model: z.number(),
      eval: z.number(),
      random: z.number(),
      perfect: z.number(),
      punish: z.number().optional(),
    }),
  ),
  summary: z.object({
    precision_at_50: z.object({
      model: ratio,
      eval: ratio,
      punish: ratio,
      random: ratio,
    }),
    stratified: z.record(stratifiedSchema),
  }),
});
const actionSchema = z.object({ focus: z.string(), why: z.string() });
export const briefSchema = z.object({
  park_id: z.string(),
  source: z.enum(["template", "llm"]),
  summary: z.string(),
  reasons: z.array(z.string()),
  actions: z.array(actionSchema).max(3),
  generated_at: z.string().optional(),
});
export const workItemSchema = z
  .object({
    seq: z.number(),
    park_id: z.string(),
    name: z.string(),
    town: z.string(),
    ...typeFields,
    count_approved: z.number().nullable(),
    address: z.string(),
    tel: z.string(),
    risk: riskSchema,
    // 至多 3 條，不是恆為 3。前 50 名裡有 4 園是零裁罰、純靠評鑑排上來的，
    // 真實只給得出 2 條理由（SPEC §8.9 硬規則 1）。
    reasons: z.array(z.string()).min(1).max(3),
    actions: z.array(actionSchema).max(3),
    attachments: z.object({
      punishment_count: z.number(),
      // 查無評鑑紀錄的新立案園所是 null，不是 0。
      evaluation_count: z.number().nullable(),
    }),
  })
  .transform(normalizeType);
export const worklistSchema = z.object({
  week: z.string(),
  generated_at: z.string(),
  model: modelSchema,
  items: z.array(workItemSchema),
});
export type Park = z.infer<typeof parkSchema>;
export type ParkRow = z.infer<typeof parkRowSchema>;
export type Reason = z.infer<typeof reasonSchema>;
export type Meta = z.infer<typeof metaSchema>;
export type Tier = z.infer<typeof tierSchema>;
export type District = z.infer<typeof districtsSchema>["items"][number];
export type Curve = z.infer<typeof curveSchema>;
export type MapData = z.infer<typeof mapSchema>;
export type WorkItem = z.infer<typeof workItemSchema>;
