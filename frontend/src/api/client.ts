import type { z } from "zod";
export class ApiError extends Error {
  constructor(
    public status: number,
    public requestId: string,
    message = "資料載入失敗",
  ) {
    super(message);
  }
}
export const isMock =
  import.meta.env.VITE_API_BASE === "mock" || import.meta.env.MODE === "mock";
export async function fetchJson(
  path: string,
  signal?: AbortSignal,
  base = import.meta.env.VITE_API_BASE ?? "/api/v1",
): Promise<unknown> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    const timer = setTimeout(abort, 10_000);
    try {
      const response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
        signal: controller.signal,
      });
      const rid = response.headers.get("x-request-id") ?? "未提供";
      if (response.status >= 500 && attempt === 0) {
        clearTimeout(timer);
        await new Promise((resolve) => setTimeout(resolve, 1000));
        continue;
      }
      if (!response.ok) throw new ApiError(response.status, rid);
      try {
        return { body: await response.json(), rid };
      } catch {
        throw new ApiError(200, rid, "回應格式不符合資料契約");
      }
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (signal?.aborted) throw error;
      throw new ApiError(
        0,
        "未提供",
        controller.signal.aborted
          ? "請求逾時（10 秒），請重試"
          : "無法連線，請確認網路後重試",
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
  throw new ApiError(503, "未提供");
}
export async function request<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  signal?: AbortSignal,
): Promise<z.infer<S>> {
  const result = isMock
    ? {
        body: await (await import("./mock")).mockRequest(path, signal),
        rid: "mock",
      }
    : ((await fetchJson(path, signal)) as { body: unknown; rid: string });
  const parsed = schema.safeParse(result.body);
  if (!parsed.success)
    throw new ApiError(200, result.rid, "回應格式不符合資料契約");
  return parsed.data;
}
