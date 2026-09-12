import { useEffect, useState } from "react";
import { useUrlState } from "../hooks/useUrlState";
import { useApi } from "../api/queries";
import { districtsSchema } from "../api/types";
import { isMock } from "../api/client";
import { percent, number } from "../utils/format";
import { QueryState } from "./common";
import s from "../styles/App.module.css";
function MultiSelect({
  label,
  values,
  selected,
  onChange,
}: {
  label: string;
  values: string[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  return (
    <details className={s.multi}>
      <summary>
        {label}
        {selected.length ? ` (${selected.length})` : ""}
      </summary>
      <div className={s.options}>
        <input
          type="search"
          aria-label={`搜尋${label}`}
          placeholder={`搜尋${label}`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {values
          .filter((v) => v.includes(search))
          .map((value) => (
            <label key={value}>
              <input
                type="checkbox"
                checked={selected.includes(value)}
                onChange={() =>
                  onChange(
                    selected.includes(value)
                      ? selected.filter((v) => v !== value)
                      : [...selected, value],
                  )
                }
              />
              {value}
            </label>
          ))}
      </div>
    </details>
  );
}
export function FilterBar({
  total,
  population,
  map = false,
}: {
  total?: number;
  population: number;
  map?: boolean;
}) {
  const { params, update, clear } = useUrlState();
  const districts = useApi("/districts", districtsSchema);
  const [search, setSearch] = useState(params.get("q") ?? "");
  const urlSearch = params.get("q") ?? "";
  useEffect(() => {
    setSearch(urlSearch);
  }, [urlSearch]);
  useEffect(() => {
    if (search === urlSearch) return;
    const timer = setTimeout(() => update("q", search), 300);
    return () => clearTimeout(timer);
  }, [search, urlSearch]);
  const chips = [...params.entries()].filter(([key]) =>
    [
      "town",
      "type",
      "tier",
      "has_finance_flag",
      "include_inactive",
      "q",
    ].includes(key),
  );
  return (
    <section className={s.filters} data-filters aria-label="園所篩選">
      <div className={s.filterRow}>
        {!map && (
          <label className={s.search}>
            搜尋園名
            <input
              type="search"
              placeholder="輸入園名關鍵字"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        )}
        <QueryState query={districts}>
          {(data) => (
            <MultiSelect
              label="行政區"
              values={data.items
                .map((d) => d.town)
                .sort((a, b) => a.localeCompare(b, "zh-Hant"))}
              selected={params.getAll("town")}
              onChange={(v) => update("town", v)}
            />
          )}
        </QueryState>
        {!map && (
          <MultiSelect
            label="設立別"
            values={["公立", "私立", "非營利"]}
            selected={params.getAll("type")}
            onChange={(v) => update("type", v)}
          />
        )}
        <MultiSelect
          label="分級"
          values={["高", "中", "低"]}
          selected={params.getAll("tier")}
          onChange={(v) => update("tier", v)}
        />
        {!map && (
          <>
            <label>
              <input
                type="checkbox"
                checked={params.get("has_finance_flag") === "true"}
                onChange={(e) =>
                  update("has_finance_flag", e.target.checked ? "true" : "")
                }
              />{" "}
              僅財務旗標
            </label>
            <label
              title={!isMock ? "目前正式 API 僅提供營運中園所" : undefined}
            >
              <input
                type="checkbox"
                disabled={!isMock}
                checked={params.get("include_inactive") === "true"}
                onChange={(e) =>
                  update("include_inactive", e.target.checked ? "true" : "")
                }
              />{" "}
              包含已停辦{!isMock && "（API 尚未支援）"}
            </label>
          </>
        )}
      </div>
      <div className={s.chips}>
        {chips.map(([key, value]) => (
          <button
            key={`${key}-${value}`}
            className={s.chip}
            aria-label={`移除${value}`}
            onClick={() => {
              if (key === "q") setSearch("");
              update(
                key,
                params.getAll(key).filter((v) => v !== value),
              );
            }}
          >
            {key === "has_finance_flag"
              ? "財務旗標"
              : key === "include_inactive"
                ? "已停辦"
                : value}{" "}
            ×
          </button>
        ))}
        <button
          onClick={() => {
            setSearch("");
            clear();
          }}
        >
          清除全部
        </button>
        <span className={s.resultCount} aria-live="polite">
          {total === undefined
            ? "正在取得筆數…"
            : `共 ${number(total)} 筆 · 佔母體 ${percent(total / population)}`}
        </span>
      </div>
    </section>
  );
}
export function EmptyState() {
  const { params, update, clear } = useUrlState();
  return (
    <div className={`${s.panel} ${s.empty}`}>
      <h2>沒有符合條件的園所</h2>
      <p>
        目前條件：
        {[...params.entries()]
          .filter(([k]) => ["q", "town", "type", "tier"].includes(k))
          .map(([, v]) => v)
          .join(" + ") || "目前頁碼或資料範圍"}
        。請減少篩選條件或返回第一頁。
      </p>
      <button onClick={() => update("tier", "")}>清除分級篩選</button>{" "}
      <button onClick={clear}>清除全部</button>
    </div>
  );
}
