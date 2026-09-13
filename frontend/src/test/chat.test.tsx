import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ChatWidget } from "../components/ChatWidget";
import { postChat } from "../api/client";
afterEach(() => vi.unstubAllGlobals());
const park = {
  park_id: "p1",
  name: "測試幼兒園",
  town: "板橋區",
  institution_type: "私立",
  is_active: 1,
  tier: "高",
  rank: 3,
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "x-request-id": "REQ-1" },
  });
function renderWidget(path = "/overview") {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <ChatWidget />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "稽查助手" }));
}
function send(text: string) {
  fireEvent.change(screen.getByLabelText("輸入問題"), {
    target: { value: text },
  });
  fireEvent.click(screen.getByRole("button", { name: "送出" }));
}
it("posts the question and shows answer, park, citations and unverified warning", async () => {
  const fetch = vi.fn().mockResolvedValue(
    json({
      source: "llm",
      answer: "總結\n- 查師生比",
      park,
      citations: [
        {
          law: "幼兒教育及照顧法",
          article: "第16條",
          snippet: "《幼兒教育及照顧法》第16條\n每班以三十人為限。",
          url: null,
        },
      ],
      unverified_refs: ["《不存在法》"],
    }),
  );
  vi.stubGlobal("fetch", fetch);
  renderWidget();
  send("測試幼兒園最近如何");
  expect(await screen.findByText("• 查師生比")).toBeInTheDocument();
  expect(screen.getByText(/測試幼兒園 · 高風險 · 第 3 名/)).toBeInTheDocument();
  expect(screen.getByText("參考條文 1 則")).toBeInTheDocument();
  expect(screen.getByText(/請自行查證/)).toHaveTextContent("《不存在法》");
  const [url, init] = fetch.mock.calls[0];
  expect(url).toMatch(/\/api\/v1\/chat$/);
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({ message: "測試幼兒園最近如何" });
});
it("re-asks with park_id when a candidate is picked", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      json({
        source: "candidates",
        answer: "找到 2 家",
        candidates: [park, { ...park, park_id: "p2", town: "新店區" }],
      }),
    )
    .mockResolvedValueOnce(json({ source: "llm", answer: "好", park }));
  vi.stubGlobal("fetch", fetch);
  renderWidget();
  send("測試幼兒園");
  fireEvent.click(await screen.findByRole("button", { name: /新店區/ }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
    message: "測試幼兒園",
    park_id: "p2",
  });
});
it("explains throttling and disabled assistant without retrying", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json({ message: "Rate Exceeded." }, 429))
    .mockResolvedValueOnce(
      json(
        {
          error: { code: "ASSISTANT_DISABLED", message: "x", request_id: "r" },
        },
        503,
      ),
    );
  vi.stubGlobal("fetch", fetch);
  renderWidget();
  send("第一題");
  expect(await screen.findByRole("alert")).toHaveTextContent("助理忙碌中");
  send("第二題");
  await waitFor(() =>
    expect(screen.getAllByRole("alert")[1]).toHaveTextContent(
      "稽查助手尚未啟用",
    ),
  );
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("rejects a response that breaks the contract", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ source: "oops" })));
  await expect(postChat({ message: "x" })).rejects.toMatchObject({
    message: "回應格式不符合資料契約",
  });
});
it("tells the inspector when laws are not retrieved yet", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        json({ source: "llm", answer: "總結", park, laws_enabled: false }),
      ),
  );
  renderWidget();
  send("測試幼兒園");
  expect(await screen.findByText(/法規知識庫尚未啟用/)).toBeInTheDocument();
});
it("turns park names inside the answer into links, including short names", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      json({
        source: "llm",
        answer:
          "建議優先稽查\n- 新北市私立景光幼兒園（中和區）：裁罰多\n- 小親親幼兒園（淡水區）",
        parks: [
          { ...park, park_id: "p1", name: "新北市私立景光幼兒園" },
          { ...park, park_id: "p2", name: "新北市私立小親親幼兒園" },
        ],
      }),
    ),
  );
  renderWidget();
  send("這週查哪間");
  const full = await screen.findByRole("link", {
    name: "新北市私立景光幼兒園",
  });
  expect(full).toHaveAttribute("href", "/park/p1");
  expect(screen.getByRole("link", { name: "小親親幼兒園" })).toHaveAttribute(
    "href",
    "/park/p2",
  );
  expect(full.closest("p")).toHaveTextContent(
    "• 新北市私立景光幼兒園（中和區）：裁罰多",
  );
});
