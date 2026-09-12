import { useSearchParams } from "react-router-dom";
export function useUrlState() {
  const [params, setParams] = useSearchParams();
  function update(key: string, values: string | string[], resetPage = true) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete(key);
      for (const value of Array.isArray(values) ? values : [values])
        if (value) next.append(key, value);
      if (resetPage && key !== "page") next.delete("page");
      return next;
    });
  }
  return { params, update, clear: () => setParams({}), setParams };
}
