import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const siteRoot = path.resolve(__dirname, "..");
const dataDir = path.join(siteRoot, "data");
const fixtureDir = path.join(siteRoot, "testdata");

const VIEWPORTS = [
  { name: "iphone-se", width: 375, height: 667 },
  { name: "iphone-14", width: 390, height: 844 },
  { name: "android", width: 360, height: 740 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1280, height: 800 },
];

function ensureFixtureData() {
  fs.mkdirSync(dataDir, { recursive: true });
  for (const file of ["index.json", "research_pack.json"]) {
    fs.copyFileSync(path.join(fixtureDir, file), path.join(dataDir, file));
  }
}

async function noHorizontalOverflow(page) {
  const metrics = await page.evaluate(() => {
    const doc = document.documentElement;
    const body = document.body;
    const cw = doc.clientWidth;
    const sw = Math.max(doc.scrollWidth, body.scrollWidth);
    return { cw, sw, overflow: sw > cw + 1 };
  });
  expect(metrics.overflow, `horizontal overflow ${metrics.sw}px > ${metrics.cw}px`).toBe(false);
}

async function waitForDesk(page) {
  await page.waitForSelector("#kpi .cell", { timeout: 20_000 });
  await page.waitForFunction(() => {
    const meta = document.getElementById("meta");
    return meta && !/^Loading/.test(meta.textContent || "");
  });
  // Charts finish sizing after Chart.js paint — wait until no overflow risk from layout.
  await expect
    .poll(async () => {
      return page.evaluate(() => {
        const wrap = document.querySelector(".chart-wrap");
        return wrap ? Math.round(wrap.getBoundingClientRect().width) : 0;
      });
    })
    .toBeGreaterThan(100);
}

test.beforeAll(() => {
  ensureFixtureData();
});

for (const vp of VIEWPORTS) {
  test(`desk has no horizontal overflow @ ${vp.name} (${vp.width}px)`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto("./", { waitUntil: "networkidle" });
    await waitForDesk(page);
    await noHorizontalOverflow(page);

    await expect(page.locator(".shell")).toBeVisible();
    await expect(page.locator("#kpi .cell").first()).toBeVisible();
    await expect(page.locator("#side-news")).toBeVisible();

    // Main column must fit inside the viewport (grid min-content bug regression).
    const mainBox = await page.locator(".main-col").boundingBox();
    expect(mainBox).toBeTruthy();
    expect(mainBox.width).toBeLessThanOrEqual(vp.width + 1);
  });
}

test("dictionary has no horizontal overflow on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("./dictionary.html", { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "Data dictionary" })).toBeVisible();
  await noHorizontalOverflow(page);
});

test("logo kit has no horizontal overflow on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("./logo.html", { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: /logo kit/i })).toBeVisible();
  await noHorizontalOverflow(page);
});

test("enrich table stacks as cards under 980px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("./", { waitUntil: "networkidle" });
  await waitForDesk(page);
  const theadDisplay = await page.locator(".enrich-table thead").evaluate((el) => getComputedStyle(el).display);
  expect(theadDisplay).toBe("none");
  const monoWrap = await page.locator(".enrich-table .mono").first().evaluate((el) => getComputedStyle(el).whiteSpace);
  expect(monoWrap).toBe("nowrap");
  await noHorizontalOverflow(page);
});

test("enrich table numbers stay nowrap on wide desk", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("./", { waitUntil: "networkidle" });
  await waitForDesk(page);
  const monoWrap = await page.locator(".enrich-table .mono").first().evaluate((el) => getComputedStyle(el).whiteSpace);
  expect(monoWrap).toBe("nowrap");
  await noHorizontalOverflow(page);
});
