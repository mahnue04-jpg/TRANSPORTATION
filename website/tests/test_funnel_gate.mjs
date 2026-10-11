import assert from "node:assert/strict";
import { createServer } from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildProduction, readFunnelPublished } from "../scripts/build-production.mjs";
import { FIRST_CUSTOMER_FUNNEL_PUBLISHED, gateFunnelRequest } from "../functions/_funnel-gate.js";
import { onRequest as startPage } from "../functions/start/index.js";
import { onRequest as startDeep } from "../functions/start/[[path]].js";
import { onRequest as guidePage } from "../functions/guides/research-memo-setup/index.js";
import { onRequest as guideDeep } from "../functions/guides/research-memo-setup/[[path]].js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const config = fs.readFileSync(path.join(root, "assets/js/site-config.js"), "utf8");
const routes = JSON.parse(fs.readFileSync(path.join(root, "_routes.json"), "utf8"));
const directUrls = [
  "/start/",
  "/start/index.html",
  "/guides/research-memo-setup/",
  "/guides/research-memo-setup/index.html",
];

function staticServer(baseDir) {
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    let rel = decodeURIComponent(url.pathname).replace(/^\/+/, "");
    if (rel === "" || rel.endsWith("/")) rel += "index.html";
    const filePath = path.resolve(baseDir, rel);
    if (filePath !== baseDir && !filePath.startsWith(baseDir + path.sep)) {
      res.writeHead(404);
      res.end("missing");
      return;
    }
    try {
      const body = await fs.promises.readFile(filePath);
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(body);
    } catch {
      res.writeHead(404);
      res.end("missing");
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port }));
  });
}

async function statusFor(port, urlPath) {
  const response = await fetch(`http://127.0.0.1:${port}${urlPath}`);
  return response.status;
}

const tests = [];
function test(name, fn) {
  tests.push([name, fn]);
}

test("the config flag and the runtime gate agree and stay off", () => {
  assert.equal(readFunnelPublished(config), false);
  assert.equal(FIRST_CUSTOMER_FUNNEL_PUBLISHED, false);
  assert.equal(readFunnelPublished(config), FIRST_CUSTOMER_FUNNEL_PUBLISHED);
  for (const rule of ["/api/*", "/start", "/start/*", "/guides/research-memo-setup", "/guides/research-memo-setup/*"]) {
    assert.ok(routes.include.includes(rule), rule);
  }
});

test("production build omits funnel pages and a true flag keeps them", () => {
  const disabledDir = fs.mkdtempSync(path.join(os.tmpdir(), "amicor-build-off-"));
  const enabledDir = fs.mkdtempSync(path.join(os.tmpdir(), "amicor-build-on-"));
  const disabled = buildProduction({ sourceDir: root, outDir: disabledDir, siteConfigSource: config });
  const enabled = buildProduction({
    sourceDir: root,
    outDir: enabledDir,
    siteConfigSource: config.replace("firstCustomerFunnel: false", "firstCustomerFunnel: true"),
  });
  assert.equal(disabled.published, false);
  assert.equal(enabled.published, true);
  for (const rel of ["start/index.html", "guides/research-memo-setup/index.html"]) {
    assert.equal(fs.existsSync(path.join(disabledDir, rel)), false, rel);
    assert.equal(fs.existsSync(path.join(enabledDir, rel)), true, rel);
  }
  assert.equal(fs.existsSync(path.join(disabledDir, "pricing/index.html")), true);
  assert.equal(fs.existsSync(path.join(disabledDir, "functions/api/leads.js")), true);
  const sitemap = fs.readFileSync(path.join(disabledDir, "sitemap.xml"), "utf8");
  assert.equal(sitemap.includes("/start/"), false);
  assert.equal(sitemap.includes("/guides/"), false);
  for (const page of ["index.html", "pricing/index.html", "business-services/index.html"]) {
    const html = fs.readFileSync(path.join(disabledDir, page), "utf8");
    assert.equal(html.includes('href="/start/"'), false, page);
    assert.equal(html.includes("research-memo-setup"), false, page);
  }
  return { disabledDir };
});

test("direct urls 404 in the production build and 200 in the local source preview", async () => {
  const disabledDir = fs.mkdtempSync(path.join(os.tmpdir(), "amicor-direct-off-"));
  buildProduction({ sourceDir: root, outDir: disabledDir, siteConfigSource: config });
  const production = await staticServer(disabledDir);
  const preview = await staticServer(root);
  try {
    for (const urlPath of directUrls) {
      assert.equal(await statusFor(production.port, urlPath), 404, urlPath);
      assert.equal(await statusFor(preview.port, urlPath), 200, urlPath);
    }
    assert.equal(await statusFor(production.port, "/pricing/"), 200);
  } finally {
    production.server.close();
    preview.server.close();
  }
});

test("the function denies direct urls unless local preview is explicit", async () => {
  const handlers = [startPage, startDeep, guidePage, guideDeep, gateFunnelRequest];
  for (const handler of handlers) {
    let nextCalls = 0;
    const denied = await handler({
      env: {},
      next: async () => {
        nextCalls += 1;
        return new Response("page", { status: 200 });
      },
    });
    assert.equal(denied.status, 404);
    assert.equal(nextCalls, 0);
    const envOnly = await handler({
      env: { FIRST_CUSTOMER_FUNNEL: "true" },
      next: async () => new Response("page", { status: 200 }),
    });
    assert.equal(envOnly.status, 404);
    const preview = await handler({
      env: { AMICOR_FUNNEL_PREVIEW: "local" },
      next: async () => new Response("preview", { status: 200 }),
    });
    assert.equal(preview.status, 200);
    assert.equal(await preview.text(), "preview");
  }
});

let failed = 0;
for (const [name, fn] of tests) {
  try {
    await fn();
    console.log(`PASS ${name}`);
  } catch (err) {
    failed += 1;
    console.error(`FAIL ${name}`);
    console.error(err);
  }
}
console.log(`GATE_TESTS_PASSED=${tests.length - failed}`);
console.log(`GATE_TESTS_FAILED=${failed}`);
if (failed) process.exit(1);
