import { useQuery } from "@tanstack/react-query";
import type { z } from "zod";
import { request } from "./client";
import { metaSchema, parkSchema } from "./types";
export function useApi<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  enabled = true,
) {
  return useQuery<z.infer<S>>({
    queryKey: [path],
    queryFn: ({ signal }) => request(path, schema, signal),
    enabled,
    staleTime: path.startsWith("/parks/") ? 60_000 : 300_000,
    retry: false,
  });
}
export const useMeta = () => useApi("/meta", metaSchema);
export const usePark = (id: string, enabled = true) =>
  useApi(`/parks/${encodeURIComponent(id)}`, parkSchema, enabled);
