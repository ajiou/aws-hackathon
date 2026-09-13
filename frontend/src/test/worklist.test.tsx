import { afterEach, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { readFileSync } from "node:fs";
import Worklist from "../pages/Worklist";
const sheet = JSON.parse(readFileSync("mock/worklist.json", "utf8"));
const meta = JSON.parse(readFileSync("mock/meta.json", "utf8"));
afterEach(() => vi.unstubAllGlobals());
function mount(search: string) {
  // 派工單頁除了 /worklist 也會抓 /meta（成效數字旁邊那句「這是回測量的」
  // 來自 meta.model_basis），所以要依網址分流，不能一律回同一份 JSON。
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(String(url).includes("/meta") ? meta : sheet),
          {
            headers: { "content-type": "application/json" },
          },
        ),
      ),
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/worklist${search}`]}>
        <Worklist />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
// 單園派工單必須跟整份派工單是同一份資料的子集，不是另一條產生路徑。
// 這是重點：稽查人員手上那張紙跟系統列出來的那份如果對不起來，派工單就失去
// 當作依據的資格。所以測「篩出來的那一筆逐欄等於整份裡的同一筆」。
it("filters the sheet to one park and keeps that park's original sequence number", async () => {
  const target = sheet.items[7];
  const { container } = mount(
    `?week=${sheet.week}&park=${encodeURIComponent(target.park_id)}`,
  );
  const items = await screen.findAllByText(target.name);
  expect(items.length).toBeGreaterThan(0);
  expect(container.querySelectorAll("[data-work-item]")).toHaveLength(1);
  // seq 保留整份名單裡的序號（第 8 名就印 8.），不會因為只印一頁就變成 1.
  expect(container.querySelector("[data-work-item] h3")?.textContent).toContain(
    `${target.seq}.`,
  );
  for (const reason of target.reasons)
    expect(screen.getByText(reason)).toBeInTheDocument();
});
it("renders every item when no park filter is present", async () => {
  const { container } = mount(`?week=${sheet.week}`);
  await screen.findAllByText(sheet.items[0].name);
  expect(container.querySelectorAll("[data-work-item]")).toHaveLength(
    sheet.items.length,
  );
});
// 直接開一個不在名單上的園（書籤、轉寄連結）是正常狀態，不是錯誤。
it("explains an absent park instead of rendering a blank sheet", async () => {
  const { container } = mount(`?week=${sheet.week}&park=not-on-the-sheet`);
  expect(await screen.findByText(/不在.*名派工名單內/)).toBeInTheDocument();
  expect(container.querySelectorAll("[data-work-item]")).toHaveLength(0);
});
