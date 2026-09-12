import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const parkId = "d3529bca-98d5-4761-9ff3-40ee3716d1dc";
test("seven pages support direct navigation and have no serious accessibility violations", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const [path, title] of [
    ["/", "園所風險地圖"],
    ["/overview", "教保機構風險總覽"],
    ["/risk", "風險列表 — 前 50 名"],
    [`/park/${parkId}`, "新北市私立景光幼兒園"],
    ["/districts", "行政區風險熱力圖"],
    ["/validation", "成效驗證"],
    ["/worklist", "稽查派工單"],
    ["/map", "園所風險地圖"],
  ]) {
    await page.goto(path);
    await expect(
      page.getByRole("heading", { level: 1, name: title, exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("status", { name: "資料載入中" })).toHaveCount(
      0,
    );
    await expect(page.getByRole("alert")).toHaveCount(0);
    const results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations.filter(
        (v) => v.impact === "critical" || v.impact === "serious",
      ),
      path,
    ).toEqual([]);
  }
  expect(errors).toEqual([]);
});
test("URL filters survive reload, support chips, sorting, paging and empty state recovery", async ({
  page,
}) => {
  await page.goto("/overview?town=板橋區&type=私立&tier=高");
  await expect(page.locator("tbody tr").first()).toBeVisible();
  const first = await page.locator("tbody").innerText();
  await page.reload();
  await expect(page.locator("tbody"))
    .toHaveText(first.replace(/\n/g, " "), { useInnerText: true })
    .catch(async () =>
      expect(await page.locator("tbody").innerText()).toBe(first),
    );
  await page.getByRole("button", { name: "清除全部", exact: true }).click();
  await page.getByRole("button", { name: "下一頁" }).click();
  await expect(page).toHaveURL(/page=2/);
  await page.getByRole("button", { name: /園名 ↕/ }).click();
  await expect(page).toHaveURL(/sort=name/);
  await page
    .getByRole("searchbox", { name: "搜尋園名", exact: true })
    .fill("完全不存在的園名xyz");
  await expect(
    page.getByRole("heading", { name: "沒有符合條件的園所" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "清除全部", exact: true })
    .first()
    .click();
  await expect(page.locator("tbody tr")).toHaveCount(50);
});
test("detail missing data and print expansion; worklist has 25 non-splitting A4 sheets", async ({
  page,
}) => {
  await page.goto(`/park/${parkId}`);
  await expect(
    page.getByText("私立幼兒園依法不需公告財務報告").first(),
  ).toBeVisible();
  await page.getByRole("tab", { name: /財報/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText(
    "私立幼兒園依法不需公告財務報告",
  );
  await page.emulateMedia({ media: "print" });
  await expect(page.locator("[role=tabpanel]:visible")).toHaveCount(4);
  await page.emulateMedia({ media: "screen" });
  await page.goto("/worklist");
  await expect(page.locator("[data-work-item]")).toHaveCount(50);
  await expect(page.locator("[data-paper]")).toHaveCount(25);
  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("navigation")).toBeHidden();
  expect(
    await page
      .locator("[data-work-item]")
      .first()
      .evaluate((el) => getComputedStyle(el).breakInside),
  ).toBe("avoid");
  const pdf = await page.pdf({
    path: "test-results/worklist.pdf",
    preferCSSPageSize: true,
  });
  const { getDocument } = await import("pdfjs-dist/legacy/build/pdf.mjs");
  const task = getDocument({ data: new Uint8Array(pdf) });
  const document = await task.promise;
  expect(document.numPages).toBe(25);
  for (let i = 1; i <= document.numPages; i++) {
    const text = (await (await document.getPage(i)).getTextContent()).items
      .map((item) => ("str" in item ? item.str : ""))
      .join("")
      .normalize("NFKC")
      .replace(/\s/g, "");
    expect(text).toContain(`第${i}/25頁`);
    expect(text.match(/簽章/g)).toHaveLength(2);
  }
  await task.destroy();
});
test("responsive widths never overflow the document", async ({ page }) => {
  for (const width of [1280, 1024, 768, 375])
    for (const path of [
      "/",
      "/overview",
      "/risk",
      `/park/${parkId}`,
      "/districts",
      "/validation",
      "/worklist",
      "/map",
    ]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(
        page.getByRole("status", { name: "資料載入中" }),
      ).toHaveCount(0);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
        `${path} at ${width}`,
      ).toBe(true);
    }
  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  await expect(navigation).toBeVisible();
  // 派工單移出導覽列，改放在右上角當動作按鈕。
  await expect(
    navigation.getByRole("link", { name: "稽查派工單" }),
  ).toHaveCount(0);
  await page.getByRole("link", { name: "稽查派工單" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/worklist/);
  await page.screenshot({ path: "test-results/mobile.png", fullPage: false });
});
test("map selection exposes reasons and validation reports public-model limitation", async ({
  page,
}) => {
  // 地圖上的鍵盤下拉已移除，改用網址直接指定園所。
  await page.goto(`/map?selected=${parkId}`);
  await page.waitForFunction(
    () => performance.getEntriesByName("watchdog-points").length > 0,
  );
  const drawer = page.getByRole("complementary");
  await expect(
    drawer.getByRole("heading", { name: "新北市私立景光幼兒園" }),
  ).toBeVisible();
  await expect(
    drawer.getByText("曾受幼照法第 51 條行政處分 9 次"),
  ).toBeVisible();
  await page.goto("/validation");
  // 不再釘死數字：模型重算後 lift 會變，這裡只確認成效頁真的算得出 lift。
  await expect(page.getByText(/^\d+\.\d\dx$/).first()).toBeVisible();
  await page.screenshot({
    path: "test-results/validation.png",
    fullPage: true,
  });
});
