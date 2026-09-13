import { useSearchParams } from "react-router-dom";
export function useUrlState() {
  const [params, setParams] = useSearchParams();
  function update(
    key: string,
    values: string | string[],
    resetPage = true,
    // 分頁切換要 replace 而不是 push：一頁四個分頁點過一輪，上一頁就要按
    // 四次才回得到風險列表。這種頁內狀態不該佔瀏覽歷史。
    replace = false,
  ) {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete(key);
        for (const value of Array.isArray(values) ? values : [values])
          if (value) next.append(key, value);
        if (resetPage && key !== "page") next.delete("page");
        return next;
      },
      { replace },
    );
  }
  function clear() {
    setParams((previous) => {
      const next = new URLSearchParams();
      const mode = previous.get("mode");
      if (mode) next.set("mode", mode);
      return next;
    });
  }
  return { params, update, clear, setParams };
}
