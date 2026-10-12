import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const playwright = await import(process.env.PLAYWRIGHT_CORE || "playwright");
const chromium = playwright.chromium || playwright.default.chromium;

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
};

function contentType(filePath) {
  return types[path.extname(filePath)] || "application/octet-stream";
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url || "/", "http://127.0.0.1");
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
    res.writeHead(200, { "Content-Type": contentType(filePath) });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end("missing");
  }
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const { port } = server.address();
const origin = `http://127.0.0.1:${port}`;
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
  const missing = await fetch(`${origin}/start/`);
  assert.equal(missing.status, 404);
  const casting = await fetch(`${origin}/casting/`);
  assert.equal(casting.status, 404);
  const direct = await fetch(`${origin}/nova-access/`);
  assert.equal(direct.status, 200);
  const directHtml = await direct.text();
  assert.match(directHtml, /Sign in to review Work &amp; Revenue/);
  assert.doesNotMatch(directHtml, /firstCustomerFunnel:\s*true/);

  await page.goto(`${origin}/`, { waitUntil: "networkidle" });
  const menu = page.getByRole("button", { name: "Menu" });
  await menu.click();
  await assert.equal(await menu.getAttribute("aria-expanded"), "true");
  const openNova = page.locator("#site-nav .nav-cta");
  const box = await openNova.boundingBox();
  assert.ok(box && box.height >= 44 && box.width >= 44);
  await openNova.click();
  await page.waitForURL(/\/nova-access\/$/);
  assert.equal(await page.locator("h1").count(), 1);
  await page.getByRole("heading", { name: "Choose a workspace" }).waitFor();
  await page.getByRole("link", { name: "Sign in to review Work & Revenue" }).waitFor();
  const work = page.locator("#work-revenue");
  await work.scrollIntoViewIfNeeded();
  assert.match(await work.innerText(), /early access/i);
  assert.match(await work.innerText(), /payment execution stay off/);
  assert.equal(await page.getByText(/casting intake/i).count(), 1);
  const shot = process.env.NOVA_ACCESS_SCREENSHOT;
  if (shot) await page.screenshot({ path: shot, fullPage: true });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${origin}/nova-access/`, { waitUntil: "networkidle" });
  const desktop = process.env.NOVA_ACCESS_DESKTOP_SCREENSHOT;
  if (desktop) await page.screenshot({ path: desktop, fullPage: true });
  const cta = page.locator(".nav-cta");
  const ctaBox = await cta.boundingBox();
  assert.ok(ctaBox && ctaBox.height >= 44);
  console.log("PASS nova-access-mobile");
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
