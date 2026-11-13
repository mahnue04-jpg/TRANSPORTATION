"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "growth-overview.js"), "utf8");

function setup(fetchImpl, initialToken = "") {
  let token = initialToken;
  let org = "test-org";
  const elements = {};
  const listeners = {};
  for (const id of [
    "growth-agent-summary", "growth-agent-status", "growth-agent-refresh",
    "growth-agent-leads", "growth-agent-conversations",
    "growth-agent-appointments", "growth-agent-transport", "sign-out"
  ]) {
    elements[id] = {
      hidden: true, disabled: false, textContent: "",
      listeners: {}, addEventListener(type, cb) { this.listeners[type] = cb; }
    };
  }
  const session = {
    getAccessToken: () => token,
    getOrganizationId: () => org,
    getAuthHeaders: () => ({ Authorization: "Bearer " + token })
  };
  const window = {
    AmiCorSession: session,
    addEventListener(type, fn) { listeners[type] = fn; }
  };
  const context = {
    document: { getElementById: id => elements[id] || null },
    window, fetch: fetchImpl,
    console
  };
  vm.runInNewContext(source, context, { filename: "growth-overview.js" });
  return { elements, listeners, setToken(v) { token = v; }, setOrg(v) { org = v; } };
}

const ok = (value) => ({ ok: true, status: 200, async json() { return value; } });
const responseFor = (url) => {
  if (url.endsWith("/flags")) return ok({ flags: { REAL_SMS_SEND: false, REAL_EMAIL_SEND: false } });
  if (url.endsWith("/leads")) return ok({ leads: [{ id: "one" }, { id: "two" }] });
  if (url.endsWith("/conversations")) return ok({ conversations: [{ id: "conv" }] });
  if (url.endsWith("/appointments")) return ok({ appointments: [] });
  throw Error("Unexpected URL: " + url);
};
async function flush() {
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
}

test("signed-out owners have no data and no API requests", async () => {
  const calls = [];
  const ui = setup(async url => { calls.push(url); return responseFor(url); });
  await flush();
  assert.equal(calls.length, 0);
  assert.equal(ui.elements["growth-agent-summary"].hidden, true);
  assert.match(ui.elements["growth-agent-status"].textContent, /Sign in/);
});

test("authenticated owner sees real API counts, not fabricated metrics", async () => {
  const calls = [];
  const ui = setup(async (url, opts) => {
    calls.push({ url, opts }); return responseFor(url);
  }, "owner-token");
  await flush();
  assert.equal(calls.length, 4);
  assert.ok(calls.every(x => x.opts.headers.Authorization === "Bearer owner-token"));
  assert.ok(calls.every(x => x.opts.cache === "no-store"));
  assert.equal(ui.elements["growth-agent-leads"].textContent, "2 (2 / 0)");
  assert.equal(ui.elements["growth-agent-conversations"].textContent, "1 (1 / 0)");
  assert.equal(ui.elements["growth-agent-appointments"].textContent, "0 (0 / 0)");
  assert.equal(ui.elements["growth-agent-transport"].textContent, "Mock / no live delivery");
  assert.equal(ui.elements["growth-agent-summary"].hidden, false);
});

test("owner sign-in event loads data without a timer", async () => {
  const ui = setup(async url => responseFor(url));
  await flush();
  ui.setToken("owner-token");
  ui.listeners["nova:workspace-signed-in"]();
  await flush();
  assert.equal(ui.elements["growth-agent-summary"].hidden, false);
});

test("403 access denial never shows stale customer counts", async () => {
  const ui = setup(async () => ({ ok: false, status: 403 }), "owner-token");
  await flush();
  assert.equal(ui.elements["growth-agent-summary"].hidden, true);
  assert.match(ui.elements["growth-agent-status"].textContent, /do not have access/);
});

test("sign-out invalidates outstanding responses and hides dashboard", async () => {
  const pending = [];
  const ui = setup((url) => new Promise(resolve => pending.push({ url, resolve })), "old-token");
  await flush();
  assert.equal(pending.length, 4);
  ui.elements["sign-out"].listeners.click();
  ui.setToken("");
  for (const item of pending) item.resolve(responseFor(item.url));
  await flush();
  assert.equal(ui.elements["growth-agent-summary"].hidden, true);
  assert.notEqual(ui.elements["growth-agent-leads"].textContent, "2 (2 / 0)");
});


test("switching organizations while requests are pending hides the old tenant data", async () => {
  const pending = [];
  const ui = setup(url => new Promise(resolve => pending.push({ url, resolve })), "owner-token");
  await flush();
  assert.equal(pending.length, 4);
  ui.setOrg("another-org");
  for (const item of pending) item.resolve(responseFor(item.url));
  await flush();
  assert.equal(ui.elements["growth-agent-summary"].hidden, true);
  assert.match(ui.elements["growth-agent-status"].textContent, /Session changed/);
  assert.notEqual(ui.elements["growth-agent-leads"].textContent, "2 (2 / 0)");
});

test("an older failed refresh cannot overwrite a newer successful refresh", async () => {
  const pending = [];
  const ui = setup(url => new Promise(resolve => pending.push({ url, resolve })), "owner-token");
  await flush();
  ui.listeners.focus();
  await flush();
  assert.equal(pending.length, 8);
  for (const item of pending.slice(4)) item.resolve(responseFor(item.url));
  await flush();
  for (const item of pending.slice(0, 4)) item.resolve({ ok: false, status: 403 });
  await flush();
  assert.equal(ui.elements["growth-agent-summary"].hidden, false);
  assert.equal(ui.elements["growth-agent-leads"].textContent, "2 (2 / 0)");
  assert.match(ui.elements["growth-agent-status"].textContent, /Owner records loaded/);
});

test("synthetic leads are labeled separately and never counted as verified clients", async () => {
  const ui = setup(async url => {
    if (url.endsWith("/leads")) return ok({ leads: [
      { id: "real", is_synthetic_demo: false },
      { id: "demo", is_synthetic_demo: true },
      { id: "unknown" }
    ] });
    return responseFor(url);
  }, "owner-token");
  await flush();
  assert.equal(ui.elements["growth-agent-leads"].textContent, "3 (2 / 1)");
  assert.match(ui.elements["growth-agent-status"].textContent, /not lifetime totals or confirmed paying customers/);
});
