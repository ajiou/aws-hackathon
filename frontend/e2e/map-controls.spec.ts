import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("top search, map filters and accessible basic information drawer work together", async ({
  page,
}) => {
  await page.goto("/map");
  const selector = page.getByLabel("選擇園所（鍵盤操作）");
  await expect(selector).toBeVisible();
  await expect
    .poll(() => selector.locator("option").count())
    .toBeGreaterThan(1);
  const total = await selector.locator("option").count();
  const types = page.getByRole("group", { name: "設立別篩選" });
  await types.getByRole("button", { name: "非營利", exact: true }).click();
  await expect(page).toHaveURL(/type=/);
  await expect(
    types.getByRole("button", { name: "非營利", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(() => selector.locator("option").count())
    .toBeLessThan(total);
  const id = await selector.locator("option").nth(1).getAttribute("value");
  await selector.selectOption(id!);
  const drawer = page.getByRole("complementary");
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("非營利", { exact: true })).toBeVisible();
  await expect(drawer.getByText("地址", { exact: true })).toBeVisible();
  await expect(drawer.getByText("電話", { exact: true })).toBeVisible();
  await expect(drawer.getByText("核定人數", { exact: true })).toBeVisible();
  const violations = (
    await new AxeBuilder({ page }).analyze()
  ).violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(violations).toEqual([]);
  const map = page.locator("[data-map-canvas]");
  const mapBox = (await map.boundingBox())!;
  const drawerBox = (await drawer.boundingBox())!;
  expect(drawerBox.x).toBeGreaterThan(mapBox.x);
  expect(drawerBox.y).toBeGreaterThanOrEqual(mapBox.y);
  expect(drawerBox.y + drawerBox.height).toBeLessThanOrEqual(
    mapBox.y + mapBox.height + 1,
  );
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(drawer).toBeVisible();
  // The drawer must allow selecting another kindergarten without closing first.
  const nextId = await selector.locator("option").nth(2).getAttribute("value");
  await selector.selectOption(nextId!);
  await expect(page).toHaveURL(new RegExp(`selected=${nextId}`));
  await expect(drawer).toBeVisible();
  await page.screenshot({ path: "test-results/map-drawer.png" });
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(selector).toBeFocused();
  await expect(page).not.toHaveURL(/selected=/);
  await page.reload();
  await expect(
    types.getByRole("button", { name: "非營利", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page
    .getByRole("searchbox", { name: "搜尋園名", exact: true })
    .fill("不存在的園所xyz");
  await expect(page).toHaveURL(/\/map\?/);
  await expect(
    page.getByRole("heading", { name: "沒有符合條件的園所" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "清除搜尋", exact: true }).click();
  await types.getByRole("button", { name: "全部", exact: true }).click();
  await expect(selector.locator("option")).toHaveCount(total);
  await expect(page.locator("[data-map-canvas]")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await page.screenshot({ path: "test-results/map-desktop.png" });
  await page.setViewportSize({ width: 375, height: 900 });
  await page.reload();
  await expect(page.locator("[data-map-canvas]")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await selector.selectOption(id!);
  await expect(drawer).toBeVisible();
  await drawer.evaluate((element) =>
    Promise.all(element.getAnimations().map((animation) => animation.finished)),
  );
  const mobileMap = (await page.locator("[data-map-canvas]").boundingBox())!;
  const mobileDrawer = (await drawer.boundingBox())!;
  expect(mobileDrawer.y).toBeGreaterThan(mobileMap.y + 100);
  expect(mobileDrawer.y + mobileDrawer.height).toBeLessThanOrEqual(
    mobileMap.y + mobileMap.height + 1,
  );
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(drawer).toBeVisible();
  await page.screenshot({
    path: "test-results/map-mobile.png",
    fullPage: true,
  });
});

test("search from another page navigates to the overview results", async ({
  page,
}) => {
  await page.goto("/validation");
  await page
    .getByRole("searchbox", { name: "搜尋園名", exact: true })
    .fill("景光");
  await page.getByRole("button", { name: "搜尋", exact: true }).click();
  await expect(page).toHaveURL(/\/\?q=/);
  await expect(
    page.getByRole("heading", { level: 1, name: "教保機構風險總覽" }),
  ).toBeVisible();
  await expect(page.locator("tbody")).toContainText("景光");
});

test("clicking a rendered kindergarten point opens its basic information", async ({
  page,
}) => {
  await page.goto("/map?q=景光");
  const canvas = page.locator("canvas.maplibregl-canvas");
  await expect(canvas).toBeVisible();
  // Locate the actual violet point in the rendered buffer, without adding test
  // hooks to the app or bypassing MapLibre's hit testing and click handler.
  let point: { x: number; y: number } | null = null;
  await expect
    .poll(async () => {
      point = await canvas.evaluate((element: HTMLCanvasElement) => {
        const gl = element.getContext("webgl2");
        if (!gl) return null;
        const pixels = new Uint8Array(element.width * element.height * 4);
        gl.readPixels(
          0,
          0,
          element.width,
          element.height,
          gl.RGBA,
          gl.UNSIGNED_BYTE,
          pixels,
        );
        let x = 0,
          y = 0,
          count = 0;
        for (let i = 0; i < pixels.length; i += 4) {
          if (
            Math.abs(pixels[i] - 124) < 3 &&
            Math.abs(pixels[i + 1] - 58) < 3 &&
            Math.abs(pixels[i + 2] - 237) < 3
          ) {
            x += (i / 4) % element.width;
            y += Math.floor(i / 4 / element.width);
            count++;
          }
        }
        return count
          ? {
              x: ((x / count) * element.clientWidth) / element.width,
              y:
                ((element.height - 1 - y / count) * element.clientHeight) /
                element.height,
            }
          : null;
      });
      return point !== null;
    })
    .toBe(true);
  await canvas.click({ position: point! });
  const drawer = page.getByRole("complementary");
  await expect(
    drawer.getByRole("heading", { name: "新北市私立景光幼兒園" }),
  ).toBeVisible();
  await expect(drawer.getByText("電話", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "關閉園所資訊" }).click();
  await expect(drawer).toHaveCount(0);
});

test("district heatmap filters the adjacent risk overview and keeps its mode", async ({
  page,
}) => {
  await page.goto("/map?mode=districts");
  await expect(
    page
      .getByRole("navigation", { name: "主要導覽" })
      .getByRole("link", { name: /行政區熱力/ }),
  ).toHaveCount(0);
  const heatmap = page.getByRole("region", {
    name: "行政區熱力圖",
    exact: true,
  });
  const overview = page.getByRole("region", {
    name: "教保機構風險總覽",
    exact: true,
  });
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  const heatBox = (await heatmap.boundingBox())!;
  const overviewBox = (await overview.boundingBox())!;
  expect(overviewBox.x).toBeGreaterThanOrEqual(heatBox.x + heatBox.width);
  await heatmap.getByRole("button", { name: /^板橋區，/ }).click();
  await expect(page).toHaveURL(/mode=districts/);
  await expect(page).toHaveURL(/town=/);
  await expect(
    overview.getByRole("button", { name: "移除板橋區" }),
  ).toBeVisible();
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  for (const town of await overview
    .locator("tbody tr td:nth-child(3)")
    .allTextContents()) {
    expect(town).toBe("板橋區");
  }
  await overview.getByRole("button", { name: /園名/ }).click();
  await expect(page).toHaveURL(/sort=name/);
  await overview.getByRole("button", { name: "清除全部", exact: true }).click();
  await expect(page).toHaveURL(/mode=districts/);
  await expect(page).not.toHaveURL(/town=/);
  await overview.getByRole("button", { name: "下一頁" }).click();
  await expect(page).toHaveURL(/page=2/);
  await page.reload();
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  await page.screenshot({ path: "test-results/map-districts.png" });
  const violations = (
    await new AxeBuilder({ page }).analyze()
  ).violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(violations).toEqual([]);
  await page
    .getByRole("searchbox", { name: "搜尋園名", exact: true })
    .fill("不存在的園所xyz");
  await expect(
    overview.getByRole("heading", { name: "沒有符合條件的園所" }),
  ).toBeVisible();
  await overview
    .getByRole("button", { name: "清除全部", exact: true })
    .last()
    .click();
  await expect(page).toHaveURL(/mode=districts/);
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  for (const width of [1024, 768, 375]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
});
