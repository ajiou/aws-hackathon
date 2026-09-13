import { useId, useState, type ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { usePark } from "../api/queries";
import {
  dimensionNames,
  type Reason,
  type Tier,
  type Park,
  type Meta,
} from "../api/types";
import { number, percent } from "../utils/format";
import s from "../styles/App.module.css";
export const unvalidated = "此維度依財務常規判斷，尚無足夠裁罰樣本可驗證";
export function Hint({ text }: { text: string }) {
  const id = useId();
  return (
    <span className={s.tooltipWrap}>
      <button className={s.hint} aria-label={text} aria-describedby={id}>
        ⓘ
      </button>
      <span role="tooltip" id={id} className={s.tooltip}>
        {text}
      </span>
    </span>
  );
}
export function TierBadge({ tier }: { tier: Tier | null }) {
  if (!tier) return <span className={s.muted}>未分級</span>;
  return (
    <span
      data-tier={tier}
      className={s.badge}
      style={{
        color: `var(--c-tier-${tier})`,
        background: `var(--c-tier-${tier}-bg)`,
        borderColor: `var(--c-tier-${tier}-border)`,
      }}
    >
      {tier}風險
    </span>
  );
}
export function ReasonList({ reasons }: { reasons: Reason[] }) {
  return reasons.length ? (
    <ul className={s.reasons}>
      {reasons.slice(0, 3).map((r, i) => (
        <li key={`${r.code}-${i}`}>
          <span>{r.label}</span>
          <span
            className={s.dimensionTag}
            style={{
              color: `var(${{ violation: "--c-tier-高", evaluation: "--c-primary", sentiment: "--c-media", operation: "--c-tier-中" }[r.dimension]})`,
            }}
          >
            {!r.validated && <Hint text={unvalidated} />}{" "}
            {dimensionNames[r.dimension]}
          </span>
        </li>
      ))}
    </ul>
  ) : (
    <p className={s.note}>尚未提供風險原因，暫不顯示分數。</p>
  );
}
export function Skeleton() {
  return (
    <div role="status" aria-label="資料載入中" className={s.panel}>
      <span className={s.srOnly}>資料載入中</span>
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className={s.skeleton} />
      ))}
    </div>
  );
}
export function ErrorState({
  error,
  retry,
}: {
  error: unknown;
  retry: () => void;
}) {
  return (
    <div role="alert" className={`${s.panel} ${s.empty}`}>
      <h2>
        {error instanceof ApiError && error.status === 404
          ? "查無此園所或資源"
          : "資料載入失敗"}
      </h2>
      <p>
        {error instanceof ApiError
          ? `${error.message}${error.status ? `（HTTP ${error.status}）` : ""}`
          : "資料暫時無法取得，請稍後重試。"}
      </p>
      <p>錯誤代碼：{error instanceof ApiError ? error.requestId : "未提供"}</p>
      <button onClick={retry}>重試</button> <Link to="/">返回總覽</Link>
    </div>
  );
}
export function QueryState<T>({
  query,
  children,
}: {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <Skeleton />;
  if (query.isError)
    return (
      <ErrorState error={query.error} retry={() => void query.refetch()} />
    );
  return <>{children(query.data)}</>;
}
export function PageHeader({
  title,
  description,
  children,
  headingLevel = 1,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
  headingLevel?: 1 | 2;
}) {
  const Heading = headingLevel === 1 ? "h1" : "h2";
  return (
    <header className={s.header}>
      <div>
        <Heading>{title}</Heading>
        {description && <p>{description}</p>}
      </div>
      <div className={`${s.actions} no-print`}>{children}</div>
    </header>
  );
}
export function CopyLink() {
  const [message, setMessage] = useState("");
  return (
    <>
      <button
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(location.href);
            setMessage("已複製連結");
          } catch {
            setMessage("請複製瀏覽器網址列中的連結");
          }
        }}
      >
        複製連結
      </button>
      <span role="status">{message}</span>
    </>
  );
}
export function ModelNote({ model }: { model: Meta["model"] }) {
  return (
    <p className={s.muted}>
      模型 {model.name} · Precision@50 = {percent(model.precision_at_50)}
      （隨機基準 {percent(model.baseline)}）
    </p>
  );
}
export function CoverageBar({ coverage }: { coverage: number }) {
  return (
    <div className={s.coverage}>
      資料涵蓋 {percent(coverage)}
      {coverage < 0.5
        ? "，此分數參考性有限"
        : coverage < 0.8
          ? "，部分維度缺資料"
          : ""}
      <div className={s.progress}>
        <span
          style={{
            width: `${coverage * 100}%`,
            background: coverage < 0.8 ? "var(--c-tier-中)" : "var(--c-text-2)",
          }}
        />
      </div>
    </div>
  );
}
export function RiskScore({ park, meta }: { park: Park; meta: Meta }) {
  const scored = park.risk.score !== null && park.reasons.length > 0;
  return (
    <section className={`${s.panel} ${s.riskBand}`} data-panel>
      {/* 橫向兩欄：左邊是分數與名次，右邊是四維度明細。
          分數不再是百分位，就是下方加權相加的結果，所以兩者並排才讀得通。 */}
      <div className={s.riskBandMain}>
        <h2>風險總分</h2>
        {park.risk.score === null && (
          <p className={s.empty}>
            已停辦，不列入排名與分級。以下仍保留該園的歷史紀錄供查詢。
          </p>
        )}
        {scored && (
          <>
            <div className={s.score}>
              {park.risk.score!.toFixed(1)} <TierBadge tier={park.risk.tier} />
            </div>
            <p className={s.scoreBasis}>
              {park.risk.score_basis ?? meta.score_basis}
              <Hint text="風險等級是在同一設立別（公立／私立／非營利）內比較切出來的，因為各類別的分數分佈本來就不同。名次則是全市合併排序。" />
            </p>
            <dl className={s.rankPair}>
              <div>
                <dt>全市名次</dt>
                <dd>
                  {park.risk.rank === null
                    ? "未排名"
                    : `${number(park.risk.rank)} / ${number(meta.population)}`}
                </dd>
              </div>
              <div>
                <dt>{park.institution_type}同類</dt>
                <dd>
                  {park.risk.peer_rank == null
                    ? "未提供"
                    : `${number(park.risk.peer_rank)} / ${number(park.risk.peer_n ?? 0)}`}
                </dd>
              </div>
            </dl>
            <div className={s.progress}>
              <span
                style={{
                  width: `${Math.min(100, park.risk.score ?? 0)}%`,
                  background: `var(--c-tier-${park.risk.tier ?? "低"})`,
                }}
              />
            </div>
          </>
        )}
        <ReasonList reasons={park.reasons} />
        {park.risk.coverage !== undefined && (
          <CoverageBar coverage={park.risk.coverage} />
        )}
      </div>
      <div className={s.riskBandSide}>
        <table className={s.dimensions}>
          <caption>四維度分數與權重</caption>
          <tbody>
            {Object.entries(park.dimensions).map(([key, dim]) => (
              <tr key={key}>
                <th scope="row">
                  {dimensionNames[key as keyof typeof dimensionNames]}{" "}
                  {!dim.validated && <Hint text={unvalidated} />}
                </th>
                <td>
                  {dim.applicable ? (
                    <>
                      <b>{dim.score === null ? "——" : dim.score.toFixed(1)}</b>{" "}
                      ×{" "}
                      {meta.weights[park.institution_type]?.[key] == null
                        ? "——"
                        : percent(meta.weights[park.institution_type][key]!)}
                      {dim.coverage < 0.8 && (
                        <p>涵蓋 {percent(dim.coverage)}</p>
                      )}
                      {dim.note && <DimensionNote note={dim.note} />}
                    </>
                  ) : (
                    <>
                      ——
                      <DimensionNote note={dim.note ?? "此維度不適用"} />
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
/** 維度備註。整段超過一行的（例如輿情引 ADR-0001 講 Precision@50）收進
 *  tooltip——稽查人員需要知道「這維度不計分」，不需要在主畫面讀回測數字。 */
function DimensionNote({ note }: { note: string }) {
  const [lead, ...rest] = note.split(/[（(]/);
  if (note.length <= 24 || !rest.length) return <p>{note}</p>;
  return (
    <p>
      {lead.trim()}
      <Hint text={note} />
    </p>
  );
}
export function ParkCard({ park }: { park: Park }) {
  return (
    <article className={s.riskRow}>
      <div className={s.rank}>{park.risk.rank}</div>
      <div>
        <div className={s.rowTitle}>
          <h2>
            <Link to={`/park/${park.park_id}`}>{park.name}</Link>
          </h2>
          <TierBadge tier={park.risk.tier} />
        </div>
        <p className={s.rowMeta}>
          {park.town} · {park.institution_type} · 核定{" "}
          {park.count_approved ?? "未提供"} 人{!park.is_active && " · 已停辦"}
        </p>
        <ReasonList reasons={park.reasons} />
        <div className={s.rowTitle}>
          {park.risk.score !== null && park.reasons.length > 0 && (
            <span>加權總分 {park.risk.score.toFixed(1)}</span>
          )}
        </div>
      </div>
    </article>
  );
}
export function ParkReasonCell({
  id,
  reasons,
}: {
  id: string;
  reasons?: Reason[];
}) {
  const query = usePark(id, !reasons);
  if (reasons) return <ReasonList reasons={reasons} />;
  return (
    <QueryState query={query}>
      {(p) => <ReasonList reasons={p.reasons} />}
    </QueryState>
  );
}
export function SafeLink({
  href,
  children,
}: {
  // null 與 undefined 都要收：財報的 pdf_url 在沒有 S3 bucket 時是明確的 null。
  href?: string | null;
  children: ReactNode;
}) {
  if (!href || !/^https?:\/\//i.test(href))
    return <span>{children}（未提供可用連結）</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}
