import { Link } from "react-router-dom";
import { useApi, useMeta } from "../api/queries";
import { topSchema } from "../api/types";
import { useUrlState } from "../hooks/useUrlState";
import {
  PageHeader,
  QueryState,
  ModelNote,
  ParkCard,
  CopyLink,
} from "../components/common";
import { EmptyState } from "../components/FilterBar";
import s from "../styles/App.module.css";
export default function Risk() {
  const { params, update } = useUrlState();
  const k = [50, 100, 200].includes(Number(params.get("k")))
    ? Number(params.get("k"))
    : 50;
  const query = useApi(`/risk/top?k=${k}`, topSchema);
  const meta = useMeta();
  return (
    <>
      <PageHeader
        title={`風險列表 — 前 ${k} 名`}
        description="依全市名次安排稽查，每筆顯示上榜原因。"
      >
        <label>
          名額{" "}
          <select value={k} onChange={(e) => update("k", e.target.value)}>
            {[50, 100, 200].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <CopyLink />
        <Link className={s.primary} to={`/worklist?k=${k}`}>
          產出本週派工單
        </Link>
      </PageHeader>
      <QueryState query={meta}>
        {(data) => <ModelNote model={data.model} />}
      </QueryState>
      <QueryState query={query}>
        {(data) =>
          data.items.length ? (
            <section aria-label="優先稽查清單">
              {data.items.map((p) => (
                <ParkCard key={p.park_id} park={p} />
              ))}
            </section>
          ) : (
            <EmptyState />
          )
        }
      </QueryState>
    </>
  );
}
