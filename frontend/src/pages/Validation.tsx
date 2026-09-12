import { useState } from "react";
import { useApi, useMeta } from "../api/queries";
import { curveSchema, type Curve } from "../api/types";
import { QueryState, PageHeader, CopyLink } from "../components/common";
import { percent, number } from "../utils/format";
import s from "../styles/App.module.css";
const lines = [
  { key: "perfect", label: "完美排序", color: "--c-line-perfect", dash: "6 4" },
  { key: "model", label: "本模型", color: "--c-line-model", dash: undefined },
  { key: "eval", label: "只看評鑑", color: "--c-line-eval", dash: "8 3" },
  { key: "random", label: "隨機抽查", color: "--c-line-random", dash: "2 4" },
] as const;
function BenefitCurve({ data }: { data: Curve }) {
  const [index, setIndex] = useState(
    Math.max(
      0,
      data.points.findIndex((p) => p.k === 50),
    ),
  );
  const points = [...data.points].sort((a, b) => a.k - b.k);
  const selected = points[Math.min(index, points.length - 1)],
    at50 = points.find((p) => p.k === 50);
  const maxK = Math.max(...points.map((p) => p.k), 1),
    maxY = Math.max(
      ...points.flatMap((p) => [p.perfect, p.model, p.eval, p.random]),
      1,
    );
  const x = (k: number) => 65 + (k / maxK) * 720,
    y = (n: number) => 330 - (n / maxY) * 270;
  return (
    <>
      <h2>稽查效益曲線</h2>
      <svg
        className={s.chart}
        data-chart
        viewBox="0 0 850 390"
        role="img"
        aria-labelledby="curve-title curve-description"
        onPointerMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const k =
            ((((e.clientX - rect.left) / rect.width) * 850 - 65) / 720) * maxK;
          const closest = points.reduce(
            (a, p, i) =>
              Math.abs(p.k - k) < Math.abs(points[a].k - k) ? i : a,
            0,
          );
          setIndex(closest);
        }}
      >
        <title id="curve-title">稽查家數與命中違規園數</title>
        <desc id="curve-description">
          四種排序的效益曲線。完整數據見下方表格，並可用滑桿選擇 K 值。
        </desc>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line
              x1="65"
              x2="785"
              y1={y(f * maxY)}
              y2={y(f * maxY)}
              stroke="var(--c-border)"
            />
            <text x="55" y={y(f * maxY) + 5} textAnchor="end">
              {Math.round(f * maxY)}
            </text>
          </g>
        ))}
        <text x="65" y="24">
          命中違規園數
        </text>
        <text x="680" y="378">
          稽查家數 K
        </text>
        {[0, 50, 100, 200, 300]
          .filter((k) => k <= maxK)
          .map((k) => (
            <text key={k} x={x(k)} y="355" textAnchor="middle">
              {k}
            </text>
          ))}
        {lines.map((line) => (
          <path
            key={line.key}
            d={[{ k: 0, model: 0, eval: 0, random: 0, perfect: 0 }, ...points]
              .map((p, i) => `${i ? "L" : "M"}${x(p.k)},${y(p[line.key])}`)
              .join(" ")}
            fill="none"
            stroke={`var(${line.color})`}
            strokeWidth={line.key === "model" ? 2 : 1.5}
            strokeDasharray={line.dash}
          />
        ))}
        {at50 && (
          <>
            <line
              x1={x(50)}
              x2={x(50)}
              y1="45"
              y2="330"
              stroke="var(--c-text-3)"
              strokeDasharray="4 4"
            />
            <circle
              cx={x(50)}
              cy={y(at50.model)}
              r="5"
              fill="var(--c-line-model)"
            />
            <circle
              cx={x(50)}
              cy={y(at50.random)}
              r="5"
              fill="var(--c-text-2)"
            />
            <text x={x(50) + 12} y="48">
              50 家：模型 {at50.model} / 隨機 {number(at50.random)}
            </text>
          </>
        )}
        {selected && (
          <line
            x1={x(selected.k)}
            x2={x(selected.k)}
            y1="60"
            y2="330"
            stroke="var(--c-text-2)"
            strokeDasharray="2 4"
          />
        )}
      </svg>
      <div className={s.legend}>
        {lines.map((l) => (
          <span key={l.key}>
            <i className={s.swatch} style={{ background: `var(${l.color})` }} />
            {l.label} · P@50{" "}
            {l.key === "perfect"
              ? at50
                ? percent(at50.perfect / 50)
                : "未提供"
              : percent(data.summary.precision_at_50[l.key])}
          </span>
        ))}
      </div>
      <label className="no-print">
        選擇稽查家數 K{" "}
        <input
          aria-label="選擇稽查家數 K"
          type="range"
          min="0"
          max={Math.max(0, points.length - 1)}
          value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
        />
      </label>
      {selected && (
        <p aria-live="polite">
          K = {selected.k}：
          {lines
            .map((l) => `${l.label} ${number(selected[l.key])} 家`)
            .join(" · ")}
        </p>
      )}
      <details data-print-expand>
        <summary>檢視曲線完整數據</summary>
        <div className={s.tableWrap} data-table-wrap>
          <table>
            <thead>
              <tr>
                <th scope="col">K</th>
                {lines.map((l) => (
                  <th key={l.key} scope="col">
                    {l.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.k}>
                  <th scope="row">{p.k}</th>
                  {lines.map((l) => (
                    <td className={s.num} key={l.key}>
                      {number(p[l.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
export default function Validation() {
  const query = useApi("/curve", curveSchema),
    meta = useMeta();
  return (
    <div className={s.limited}>
      <PageHeader
        title="成效驗證"
        description={`用 ${meta.data?.cutoff ?? "切點"} 之前的資料，預測之後誰會被裁罰。`}
      >
        <CopyLink />
        <button onClick={() => window.print()}>列印</button>
      </PageHeader>
      <QueryState query={query}>
        {(data) => {
          const p = data.summary.precision_at_50;
          const privateGroup = data.summary.stratified["私立"],
            publicGroup = data.summary.stratified["公立"];
          return (
            <>
              <div className={s.stats}>
                {[
                  [
                    "Precision@50",
                    percent(p.model),
                    `隨機基準 ${percent(p.random)}`,
                  ],
                  [
                    "相對隨機提升",
                    `${(p.model / p.random).toFixed(2)}x`,
                    `${number(p.model * 50)} 家 vs ${number(p.random * 50)} 家`,
                  ],
                  [
                    "私立組內 lift",
                    privateGroup?.lift_50 === undefined
                      ? "未提供"
                      : `${privateGroup.lift_50.toFixed(2)}x`,
                    "依私立組內 P@50 評估",
                  ],
                  [
                    "公立組內 lift",
                    publicGroup?.lift_20 === undefined
                      ? "未提供"
                      : `${publicGroup.lift_20.toFixed(2)}x`,
                    "公立組模型無效，維持例行普查",
                  ],
                ].map(([label, value, sub]) => (
                  <div className={s.stat} key={label}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                    <small>{sub}</small>
                  </div>
                ))}
              </div>
              <section className={s.panel}>
                {data.points.length ? (
                  <BenefitCurve data={data} />
                ) : (
                  <p>尚未提供效益曲線數據。</p>
                )}
              </section>
              <section className={s.panel}>
                <h2>排序方式對照</h2>
                <table>
                  <thead>
                    <tr>
                      <th scope="col">排序方式</th>
                      <th scope="col">Precision@50</th>
                      <th scope="col">相對隨機提升</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(
                      [
                        ["random", "隨機抽查（期望值）"],
                        ["punish", "只看裁罰次數"],
                        ["eval", "只看評鑑"],
                        ["model", "裁罰 + 評鑑（本模型）"],
                      ] as const
                    ).map(([key, label]) => (
                      <tr key={key}>
                        <th scope="row">{label}</th>
                        <td className={s.num}>{percent(p[key])}</td>
                        <td className={s.num}>
                          {(p[key] / p.random).toFixed(2)}x
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
              <section className={s.panel}>
                <h2>分層驗證</h2>
                <table>
                  <thead>
                    <tr>
                      <th scope="col">設立別</th>
                      <th scope="col">樣本園數</th>
                      <th scope="col">組內基準</th>
                      <th scope="col">Precision@K</th>
                      <th scope="col">lift</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.summary.stratified).map(
                      ([name, g]) => {
                        const k =
                          g.lift_50 !== undefined
                            ? 50
                            : g.lift_20 !== undefined
                              ? 20
                              : 10;
                        return (
                          <tr key={name}>
                            <th scope="row">{name}</th>
                            <td className={s.num}>{g.n}</td>
                            <td className={s.num}>{percent(g.baseline)}</td>
                            <td className={s.num}>
                              P@{k} ={" "}
                              {percent(
                                (k === 50
                                  ? g.p_at_50
                                  : k === 20
                                    ? g.p_at_20
                                    : g.p_at_10) ?? 0,
                              )}
                            </td>
                            <td className={s.num}>
                              {(k === 50
                                ? g.lift_50
                                : k === 20
                                  ? g.lift_20
                                  : g.lift_10
                              )?.toFixed(2) ?? "未提供"}
                              x
                            </td>
                          </tr>
                        );
                      },
                    )}
                  </tbody>
                </table>
              </section>
              <section className={s.panel}>
                <h2>方法與限制</h2>
                <ul>
                  <li>
                    本次曲線母體 {number(data.population)} 園、正樣本{" "}
                    {data.positives}{" "}
                    園。營運中清單與歷史回測分層可能採不同母體，請依資料版本解讀。
                  </li>
                  <li>
                    特徵僅使用 {meta.data?.cutoff ?? "切點"}{" "}
                    之前的資料，標籤為之後是否被裁罰。
                  </li>
                  <li>
                    Precision@50 對應前 50
                    個稽查名額，不能解讀為單一園所違規機率。
                  </li>
                  <li>
                    公立園組內模型無效（本次 lift{" "}
                    {publicGroup?.lift_20?.toFixed(2) ?? "未提供"}
                    x），建議維持例行普查。
                  </li>
                  <li>
                    非營利組樣本小；營運維度依財務常規判斷，尚未通過裁罰樣本驗證。
                  </li>
                </ul>
              </section>
            </>
          );
        }}
      </QueryState>
    </div>
  );
}
