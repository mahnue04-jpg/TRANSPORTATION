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

const server = createServer(async (req, res) => {
  if (req.url.startsWith("/api/leads") && req.method === "POST") {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const request = new Request("https://getamicor.com/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: Buffer.concat(chunks),
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
  if (!filePath.startsWith(root + path.sep) && filePath !== root) {
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
const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
});

try {
  await page.goto(`http://127.0.0.1:${port}/early-access/?product=Business%20Services&intent=quote`);
  const message = page.locator("[name=message]");
  assert.equal(await message.inputValue(), "");
  assert.match(await message.getAttribute("placeholder"), /Project goal/);
  assert.equal(await page.locator("#product").inputValue(), "Business Services");

  await page.locator("[name=name]").fill("Jordan Hale");
  await page.locator("[name=company]").fill("North Star Transit");
  await page.locator("[name=email]").fill("jordan@northstar.example");
  await page.locator("[name=industry]").fill("Operations");
  await page.locator("[name=companySize]").selectOption("11-50");
  await message.fill("Need a cited research memo by Friday.");
  await page.locator("[name=consent]").check();
  await page.locator("button[type=submit]").tap();
  const success = page.locator("[data-form-success]");
  await success.waitFor({ state: "visible" });
  const firstText = await success.innerText();
  assert.match(firstText, /AMICOR saved your request/);
  assert.match(firstText, /Reference AMQ-[0-9A-F]{8}/);
  assert.match(firstText, /Email delivery was not confirmed/);
  assert.doesNotMatch(firstText, /was sent to AMICOR/);
  const reference = firstText.match(/AMQ-[0-9A-F]{8}/)[0];
  await page.screenshot({ path: "/opt/cursor/artifacts/quote-form-mobile.png", fullPage: true });

  await page.locator("[name=name]").fill("Jordan Hale");
  await page.locator("[name=company]").fill("North Star Transit");
  await page.locator("[name=email]").fill("jordan@northstar.example");
  await page.locator("[name=industry]").fill("Operations");
  await page.locator("[name=companySize]").selectOption("11-50");
  await message.fill("Need a cited research memo by Friday.");
  await page.locator("[name=consent]").check();
  await page.locator("button[type=submit]").tap();
  await page.waitForFunction((ref) => {
    const node = document.querySelector("[data-form-success]");
    return node && node.textContent.includes(ref) && node.textContent.includes("already on file");
  }, reference);
  const secondText = await success.innerText();
  assert.match(secondText, new RegExp(reference));
  assert.match(secondText, /already on file/);
  assert.match(secondText, /Email delivery was not confirmed/);
  console.log("PASS mobile quote form save and duplicate");
  console.log("MOBILE_TESTS_PASSED=1");
  console.log("MOBILE_TESTS_FAILED=0");
} catch (err) {
  console.error("FAIL mobile quote form");
  console.error(err);
  console.log("MOBILE_TESTS_PASSED=0");
  console.log("MOBILE_TESTS_FAILED=1");
  process.exitCode = 1;
} finally {
  await browser.close();
  server.close();
}
