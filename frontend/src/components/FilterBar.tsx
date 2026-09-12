import { useId, useState } from "react";
import { useUrlState } from "../hooks/useUrlState";
import { useApi } from "../api/queries";
import { districtsSchema } from "../api/types";
import { QueryState } from "./common";
import s from "../styles/App.module.css";
function MultiSelect({
  groupName,
  label,
  values,
  selected,
  onChange,
}: {
  groupName: string;
  label: string;
  values: string[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  return (
    <details className={s.multi} name={groupName}>
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
export function FilterBar({ map = false }: { map?: boolean }) {
  const dropdownGroup = useId();
  const { params, update, clear } = useUrlState();
  const districts = useApi("/districts", districtsSchema);
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
        <QueryState query={districts}>
          {(data) => (
            <MultiSelect
              groupName={dropdownGroup}
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
            groupName={dropdownGroup}
            label="設立別"
            values={["公立", "私立", "非營利"]}
            selected={params.getAll("type")}
            onChange={(v) => update("type", v)}
          />
        )}
        <MultiSelect
          groupName={dropdownGroup}
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
          </>
        )}
        <button className={s.clearFilters} onClick={clear}>
          清除全部
        </button>
      </div>
      {chips.length > 0 && (
        <div className={s.chips}>
          {chips.map(([key, value]) => (
            <button
              key={`${key}-${value}`}
              className={s.chip}
              aria-label={`移除${value}`}
              onClick={() => {
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
        </div>
      )}
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
