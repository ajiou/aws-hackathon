import { chromium } from "@playwright/test";
import lighthouse from "lighthouse";
import { launch } from "chrome-launcher";
import { mkdir, writeFile } from "node:fs/promises";

await mkdir("test-results", { recursive: true });
const chrome = await launch({
  chromePath: chromium.executablePath(),
  chromeFlags: ["--headless", "--no-sandbox"],
});
try {
  const result = await lighthouse(
    "http://127.0.0.1:4173/",
    {
      port: chrome.port,
      output: "html",
      onlyCategories: ["performance"],
      logLevel: "error",
    },
    {
      extends: "lighthouse:default",
      settings: {
        formFactor: "desktop",
        screenEmulation: {
          mobile: false,
          width: 1280,
          height: 900,
          deviceScaleFactor: 1,
          disabled: false,
        },
        throttling: {
          rttMs: 40,
          throughputKbps: 10240,
          cpuSlowdownMultiplier: 1,
        },
      },
    },
  );
  await writeFile("test-results/lighthouse.html", result.report);
  const metrics = {
    performance: result.lhr.categories.performance.score * 100,
    lcp_ms: result.lhr.audits["largest-contentful-paint"].numericValue,
    total_blocking_ms: result.lhr.audits["total-blocking-time"].numericValue,
  };
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({
      viewport: { width: 1280, height: 900 },
    });
    await page.goto("http://127.0.0.1:4173/map");
    await page.waitForFunction(
      () => performance.getEntriesByName("watchdog-points").length > 0,
      undefined,
      { timeout: 30000 },
    );
    metrics.map_points_ms = await page.evaluate(
      () => performance.getEntriesByName("watchdog-points").at(-1).duration,
    );
    await page.screenshot({ path: "test-results/map.png" });
  } finally {
    await browser.close();
  }
  await writeFile(
    "test-results/performance.json",
    JSON.stringify(metrics, null, 2),
  );
  console.log(metrics);
} finally {
  await chrome.kill();
}
