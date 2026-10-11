import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { handleLead } from "../functions/api/leads.js";

const playwright = await import(process.env.PLAYWRIGHT_CORE || "playwright-core");
const chromium = playwright.chromium || playwright.default.chromium;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
};

class MemoryKv {
  constructor() {
    this.items = new Map();
  }

  async get(key) {
    return this.items.get(key) || null;
  }

  async put(key, value) {
    this.items.set(key, value);
  }
}

const store = new MemoryKv();
let lastBody = null;
const server = createServer(async (req, res) => {
  if (req.url.startsWith("/api/leads") && req.method === "POST") {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const raw = Buffer.concat(chunks);
    lastBody = JSON.parse(raw.toString("utf8"));
    const request = new Request("https://getamicor.com/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: raw,
    });
    const response = await handleLead(request, { AMICOR_LEADS: store });
    res.writeHead(response.status, { "Content-Type": "application/json; charset=utf-8" });
    res.end(Buffer.from(await response.arrayBuffer()));
    return;
  }
  const url = new URL(req.url, "http://127.0.0.1");
  let rel = decodeURIComponent(url.pathname).replace(/^\/+/, "");
  if (rel === "" || rel.endsWith("/")) rel += "index.html";
  const filePath = path.resolve(root, rel);
  if (!filePath.startsWith(root + path.sep)) {
    res.writeHead(404);
    res.end("missing");
    return;
  }
  try {
    const body = await readFile(filePath);
    res.writeHead(200, { "Content-Type": types[path.extname(filePath)] || "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end("missing");
  }
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const { port } = server.address();
const launchOptions = {
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
};
if (process.env.PLAYWRIGHT_CHANNEL) launchOptions.channel = process.env.PLAYWRIGHT_CHANNEL;
const browser = await chromium.launch(launchOptions);
const page = await browser.newPage({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
});

try {
  await page.goto(`http://127.0.0.1:${port}/start/`);
  const choiceNames = await page.locator("[data-plan-choice]").allInnerTexts();
  assert.deepEqual(choiceNames.map((name) => name.trim()), [
    "Select Explore & scope",
    "Select Starter Task",
    "Select Launch Operations",
    "Select Business Operations",
  ]);
  await page.locator("[name=name]").fill("Jordan Hale");
  await page.locator("[name=company]").fill("North Star Transit");
  await page.locator("[name=email]").fill("jordan@northstar.example");
  await page.locator("[name=industry]").fill("Operations");
  await page.locator("[name=companySize]").selectOption("11-50");
  await page.locator("[name=message]").fill("Need a cited research memo by Friday.");
  await page.locator("[name=consent]").check();
  await page.locator("button[type=submit]").tap();
  await page.locator("[data-form-error]").waitFor({ state: "visible" });
  assert.match(await page.locator("[data-form-error]").innerText(), /Choose a starting option/);
  await page.getByRole("button", { name: "Select Starter Task" }).tap();
  await page.waitForFunction(() => document.querySelector("[data-plan-status]").textContent.includes("Starter Task ($49 one-time)"));
  await page.locator("[name=name]").fill("Jordan Hale");
  await page.locator("[name=company]").fill("North Star Transit");
  await page.locator("[name=email]").fill("jordan@northstar.example");
  await page.locator("[name=industry]").fill("Operations");
  await page.locator("[name=companySize]").selectOption("11-50");
  await page.locator("[name=message]").fill("Need a cited research memo by Friday.");
  await page.locator("[name=consent]").check();
  await page.locator("button[type=submit]").tap();
  const success = page.locator("[data-form-success]");
  await success.waitFor({ state: "visible" });
  const text = await success.innerText();
  assert.match(text, /Reference AMQ-[0-9A-F]{8}/);
  assert.match(text, /Email delivery was not confirmed/);
  assert.doesNotMatch(text, /notification email was sent/);
  assert.equal(await page.locator("[data-plan-choice]").nth(1).getAttribute("aria-pressed"), "true");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  assert.equal(overflow, false);
  assert.match(lastBody.message, /Starting option: Starter Task \(\$49 one-time\)/);
  assert.match(lastBody.message, /cited research memo/);
  assert.equal(lastBody.product, "Nova Operations Agent");
  await page.screenshot({ path: "/opt/cursor/artifacts/start-funnel-mobile.png", fullPage: true });
  await page.goto(`http://127.0.0.1:${port}/guides/research-memo-setup/`);
  const disclosure = await page.locator("[data-affiliate-disclosure]").innerText();
  assert.match(disclosure, /Affiliate enrollment: pending/);
  assert.match(disclosure, /no affiliate links/);
  assert.match(disclosure, /no commission/);
  assert.match(disclosure, /no income claim/);
  assert.doesNotMatch(disclosure, /\$/);
  const guideOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  assert.equal(guideOverflow, false);
  console.log("PASS mobile first-customer funnel");
  console.log("FUNNEL_MOBILE_PASSED=1");
  console.log("FUNNEL_MOBILE_FAILED=0");
} catch (err) {
  console.error("FAIL mobile first-customer funnel");
  console.error(err);
  console.log("FUNNEL_MOBILE_PASSED=0");
  console.log("FUNNEL_MOBILE_FAILED=1");
  process.exitCode = 1;
} finally {
  await browser.close();
  server.close();
}
