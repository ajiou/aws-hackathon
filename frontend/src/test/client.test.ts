import { afterEach, describe, it, expect, vi } from "vitest";
import { fetchJson, ApiError } from "../api/client";
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe("API client", () => {
  it("retries a 503 once and preserves the response request id", async () => {
    vi.useFakeTimers();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockResolvedValueOnce(
        new Response('{"ok":true}', { headers: { "x-request-id": "REQ-123" } }),
      );
    vi.stubGlobal("fetch", fetch);
    const result = fetchJson("/meta", undefined, "/api/v1");
    await vi.advanceTimersByTimeAsync(1000);
    await expect(result).resolves.toEqual({
      body: { ok: true },
      rid: "REQ-123",
    });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("never retries a 404 and never exposes server error text", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response('{"error":"private-bucket secret stack trace"}', {
          status: 404,
          headers: { "x-request-id": "REQ-404" },
        }),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(fetchJson("/parks/nope")).rejects.toMatchObject({
      status: 404,
      requestId: "REQ-404",
      message: "資料載入失敗",
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("stops after the second 5xx", async () => {
    vi.useFakeTimers();
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 503 }));
    vi.stubGlobal("fetch", fetch);
    const result = fetchJson("/meta").catch((e) => e);
    await vi.advanceTimersByTimeAsync(1000);
    expect(await result).toBeInstanceOf(ApiError);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("times out a stalled request at ten seconds", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url, init) =>
          new Promise((_resolve, reject) =>
            init.signal.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            ),
          ),
      ),
    );
    const result = fetchJson("/meta").catch((e) => e);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(await result).toMatchObject({
      status: 0,
      message: "請求逾時（10 秒），請重試",
    });
  });
});
