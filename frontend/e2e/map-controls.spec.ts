import { test, expect, type Locator, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// 直接點地圖上的行政區：不同投影位置都試一次，避開海面、行政區邊界與園所點位。
async function clickAnyDistrict(page: Page, canvas: Locator) {
  const box = (await canvas.boundingBox())!;
  await expect
    .poll(
      async () => {
        for (const [fx, fy] of [
          [0.5, 0.6],
          [0.45, 0.5],
          [0.55, 0.7],
          [0.4, 0.45],
        ]) {
          if (/town=/.test(page.url())) break;
          await canvas.click({
            position: { x: box.width * fx, y: box.height * fy },
          });
          await page.waitForTimeout(250);
        }
        return /town=/.test(page.url());
      },
      { timeout: 30_000 },
    )
    .toBe(true);
}

test("top search, map filters and accessible basic information panel work together", async ({
  page,
}) => {
  await page.goto("/map");
  const mapRegion = page.getByRole("region", { name: "園所風險地圖" });
  // 地圖上的鍵盤下拉已移除，園所數量改看地圖頁尾的即時計數。
  const shown = async () =>
    Number(
      (await mapRegion.locator("strong").first().innerText()).replace(/,/g, ""),
    );
  await expect.poll(shown).toBeGreaterThan(1);
  const total = await shown();
  const types = page.getByRole("group", { name: "設立別篩選" });
  await types.getByRole("button", { name: "非營利", exact: true }).click();
  await expect(page).toHaveURL(/type=/);
  await expect(
    types.getByRole("button", { name: "非營利", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect.poll(shown).toBeLessThan(total);
  const overview = page.getByRole("region", {
    name: "教保機構風險總覽",
    exact: true,
  });
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  const ids = await overview
    .locator("tbody tr th a")
    .evaluateAll((links) =>
      links.map((a) => a.getAttribute("href")!.replace("/park/", "")),
    );
  const drawer = page.getByRole("complementary");
  // 名單上的園所不一定都有座標，挑到第一個開得起來的為止。
  let opened = "";
  for (const id of ids.slice(0, 4)) {
    await page.goto(
      `/map?${new URLSearchParams({ type: "非營利", selected: id })}`,
    );
    const shows = await drawer
      .waitFor({ state: "visible", timeout: 4000 })
      .then(() => true)
      .catch(() => false);
    if (shows) {
      opened = id;
      break;
    }
  }
  expect(opened).not.toBe("");
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
  // 園所詳情是版面右欄，不再浮在地圖上：與地圖並排、頂端對齊。
  expect(drawerBox.x).toBeGreaterThanOrEqual(mapBox.x + mapBox.width);
  expect(Math.abs(drawerBox.y - mapBox.y)).toBeLessThanOrEqual(4);
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(drawer).toBeVisible();
  await page.screenshot({ path: "test-results/map-drawer.png" });
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(page).not.toHaveURL(/selected=/);
  await page.reload();
  await expect(
    types.getByRole("button", { name: "非營利", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  // 頂端搜尋是 300ms debounce，reload 後太早輸入會打在還沒接上事件的 input 上，
  // 所以重填到網址真的帶上 q 為止。
  await expect(async () => {
    await page
      .getByRole("searchbox", { name: "搜尋園名", exact: true })
      .fill("不存在的園所xyz");
    await expect(page).toHaveURL(/q=/, { timeout: 2000 });
  }).toPass({ timeout: 15_000 });
  await expect(page).toHaveURL(/\/map\?/);
  // 地圖與右側總覽現在同頁，兩邊都有空狀態標題，斷言要指明是地圖那一個。
  await expect(
    mapRegion.getByRole("heading", { name: "沒有符合條件的園所" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "清除搜尋", exact: true }).click();
  await types.getByRole("button", { name: "全部", exact: true }).click();
  await expect.poll(shown).toBe(total);
  await expect(page.locator("[data-map-canvas]")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await page.screenshot({ path: "test-results/map-desktop.png" });
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto(`/map?selected=${opened}`);
  await expect(drawer).toBeVisible();
  const mobileMap = (await page.locator("[data-map-canvas]").boundingBox())!;
  const mobileDrawer = (await drawer.boundingBox())!;
  // 窄螢幕時右欄落到地圖下方，不覆蓋地圖。
  expect(mobileDrawer.y).toBeGreaterThanOrEqual(
    mobileMap.y + mobileMap.height - 2,
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
  await page.goto("/worklist");
  // 同上：輸入太早會打在還沒接上事件的 input，重試到網址真的帶上 q 為止。
  await expect(async () => {
    await page
      .getByRole("searchbox", { name: "搜尋園名", exact: true })
      .fill("景光");
    await page.getByRole("button", { name: "搜尋", exact: true }).click();
    await expect(page).toHaveURL(/\/overview\?q=/, { timeout: 2000 });
  }).toPass({ timeout: 15_000 });
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

test("district heat layer shares the map canvas and filters the adjacent overview", async ({
  page,
}) => {
  await page.goto("/map?mode=districts");
  await expect(
    page
      .getByRole("navigation", { name: "主要導覽" })
      .getByRole("link", { name: /行政區熱力/ }),
  ).toHaveCount(0);
  const layers = page.getByRole("group", { name: "圖層切換" });
  await expect(
    layers.getByRole("button", { name: "行政區熱力" }),
  ).toHaveAttribute("aria-pressed", "true");
  const canvas = page.locator("canvas.maplibregl-canvas");
  await expect(canvas).toBeVisible();
  const overview = page.getByRole("region", {
    name: "教保機構風險總覽",
    exact: true,
  });
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  const mapBox = (await page.locator("[data-map-canvas]").boundingBox())!;
  const overviewBox = (await overview.boundingBox())!;
  expect(overviewBox.x).toBeGreaterThanOrEqual(mapBox.x + mapBox.width);
  await clickAnyDistrict(page, canvas);
  await expect(page).toHaveURL(/mode=districts/);
  await expect(page).toHaveURL(/town=/);
  // 行政區沒有下拉：地圖本身就是選行政區的介面（點該區即篩選，再點取消）。
  await expect(page.getByRole("combobox", { name: "行政區篩選" })).toHaveCount(
    0,
  );
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  // 右側欄只有列表：標題與篩選都拿掉了，空間全部讓給表格。
  await expect(
    overview.getByRole("heading", { name: "教保機構風險總覽" }),
  ).toHaveCount(0);
  await expect(overview.getByRole("group", { name: "篩選" })).toHaveCount(0);
  await expect(overview.getByRole("button", { name: "清除全部" })).toHaveCount(
    0,
  );
  // 右側欄以網站瀏覽為主，不放複製連結與列印。
  await expect(overview.getByRole("button", { name: "複製連結" })).toHaveCount(
    0,
  );
  await expect(overview.getByRole("button", { name: "列印" })).toHaveCount(0);
  // 右側欄是窄版：行政區、加權總分、裁罰次數不列出來。
  for (const column of ["行政區", "加權總分", "裁罰次數", "名次"])
    await expect(
      overview.getByRole("columnheader", { name: column }),
    ).toHaveCount(0);
  for (const column of ["分級", "園名", "設立別", "上榜原因"])
    await expect(
      overview.getByRole("columnheader", { name: new RegExp(column) }),
    ).toHaveCount(1);
  // 窄版表格要一次看完，不能左右捲。
  const wrap = overview.locator("[data-table-wrap]");
  expect(
    await wrap.evaluate((el) => el.scrollWidth - el.clientWidth),
  ).toBeLessThanOrEqual(1);
  // 右側欄與地圖同高，長表格在框內自己捲，不把頁面拉長。
  const sideBox = (await overview.boundingBox())!;
  const mapSectionBox = (await page
    .getByRole("region", { name: "園所風險地圖" })
    .boundingBox())!;
  expect(Math.abs(sideBox.height - mapSectionBox.height)).toBeLessThanOrEqual(
    4,
  );
  // 切回園所分布時保留行政區篩選，地圖同時放大到該區的園所分布。
  await layers.getByRole("button", { name: "園所分布" }).click();
  await expect(page).toHaveURL(/mode=points/);
  await expect(page).toHaveURL(/town=/);
  await page.waitForTimeout(1200);
  await page.screenshot({ path: "test-results/map-points-zoom.png" });
  // 園所分布模式下行政區仍可點：清掉篩選回到全市視野後再點一次。
  await page.getByRole("button", { name: "清除全部篩選" }).click();
  await expect(page).not.toHaveURL(/town=/);
  // 回到全市 1,178 園：長表格要在右側欄自己的框裡捲，不把整頁拉長。
  // 用 poll：每一列的「上榜原因」是各自去抓的，第一列出現時表格還在長高，
  // 單次量測會量到還沒撐滿框的中間狀態。
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  await expect
    .poll(
      async () => wrap.evaluate((el) => el.scrollHeight - el.clientHeight),
      {
        timeout: 15_000,
      },
    )
    .toBeGreaterThan(0);
  await page.waitForTimeout(900);
  await clickAnyDistrict(page, canvas);
  await expect(page).toHaveURL(/mode=points/);
  await layers.getByRole("button", { name: "行政區熱力" }).click();
  await expect(page).toHaveURL(/mode=districts/);
  // 右側欄只有分級可排序（園名不再是排序鍵）。
  await expect(
    overview.getByRole("columnheader", { name: /園名/ }).getByRole("button"),
  ).toHaveCount(0);
  await overview
    .getByRole("columnheader", { name: /分級/ })
    .getByRole("button")
    .click();
  await expect(page).toHaveURL(/dir=asc/);
  await page.getByRole("button", { name: "清除全部篩選" }).click();
  await expect(page).toHaveURL(/mode=districts/);
  await expect(page).not.toHaveURL(/town=/);
  await overview.getByRole("button", { name: "下一頁" }).click();
  await expect(page).toHaveURL(/page=2/);
  await page.reload();
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "test-results/map-districts.png" });
  const violations = (
    await new AxeBuilder({ page }).analyze()
  ).violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(violations).toEqual([]);
  // 頂端搜尋是 300ms debounce，reload 後太早輸入會打在還沒接上事件的 input 上，
  // 所以重填到網址真的帶上 q 為止。
  await expect(async () => {
    await page
      .getByRole("searchbox", { name: "搜尋園名", exact: true })
      .fill("不存在的園所xyz");
    await expect(page).toHaveURL(/q=/, { timeout: 2000 });
  }).toPass({ timeout: 15_000 });
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

// 有無裁罰紀錄的篩選：地圖點位與右側列表走的是兩條不同的路（地圖本機篩
// pun_count、列表打 /parks?punished=），所以要確認兩邊筆數一致，否則會出現
// 地圖上看得到、列表裡卻找不到的園。
test("the punishment filter keeps the map points and the adjacent list in step", async ({
  page,
}) => {
  await page.goto("/map");
  await page.waitForFunction(
    () => performance.getEntriesByName("watchdog-points").length > 0,
  );
  const overview = page.getByRole("region", {
    name: "教保機構風險總覽",
    exact: true,
  });
  const filter = page.getByRole("combobox", { name: "裁罰紀錄篩選" });
  const total = async () =>
    Number(
      (await overview.getByText(/共 [\d,]+ 筆/).innerText())
        .replace(/\D/g, "")
        .slice(-4),
    );
  const count = () => page.locator("[data-map-count]").innerText();

  await expect(filter).toHaveValue("");
  const everyone = await total();

  await filter.selectOption("true");
  await expect(page).toHaveURL(/punished=true/);
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  const punished = await total();
  expect(await count()).toContain(punished.toLocaleString());

  await filter.selectOption("false");
  await expect(page).toHaveURL(/punished=false/);
  await expect(overview.locator("tbody tr").first()).toBeVisible();
  const clean = await total();
  expect(await count()).toContain(clean.toLocaleString());

  // 兩邊互斥且加起來就是全部——沒有園被兩邊都收或都漏掉。
  expect(punished + clean).toBe(everyone);
  expect(punished).toBeGreaterThan(0);
  expect(clean).toBeGreaterThan(0);
});
