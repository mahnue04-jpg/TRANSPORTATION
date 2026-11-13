"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const script = fs.readFileSync(path.join(__dirname, "growth-review-queue.js"), "utf8");
function setup(fetchImpl, token = "", org = "owner-a") {
  let currentToken = token, currentOrg = org;
  const listeners = {}, documentListeners = {};
  function element() { return {
    textContent: "", disabled: false, children: [], listeners: {},
    addEventListener(key, cb) { this.listeners[key] = cb; },
    replaceChildren(...items) { this.children = items; }
  }; }
  const elements = Object.fromEntries([
    "growth-agent-preview-queue-load", "growth-agent-preview-queue-status",
    "growth-agent-preview-queue-list", "sign-out"
  ].map(id => [id, element()]));
  const window = {
    AmiCorSession: {
      getAccessToken: () => currentToken,
      getOrganizationId: () => currentOrg,
      getAuthHeaders: () => ({ Authorization: "Bearer " + currentToken })
    },
    addEventListener(type, cb) { listeners[type] = cb; }
  };
  const document = {
    getElementById(id) { return elements[id] || null; },
    createElement() { return element(); },
    addEventListener(type, cb) { documentListeners[type] = cb; }
  };
  let count = 0;
  const fetch = (...args) => { count++; return fetchImpl(...args); };
  vm.runInNewContext(script, { window, document, fetch }, { filename: "growth-review-queue.js" });
  return {
    elements, listeners, documentListeners, count: () => count,
    setOrg(x) { currentOrg = x; }, setToken(x) { currentToken = x; },
    click() { return elements["growth-agent-preview-queue-load"].listeners.click(); },
    signOut() { return elements["sign-out"].listeners.click(); }
  };
}
const ok = items => ({ ok: true, status: 200, json: async () => ({ items }) });
test("signed-out does not fetch previews", async () => {
  const ui = setup(() => { throw Error("Must not fetch"); });
  await ui.click();
  assert.equal(ui.count(), 0);
  assert.match(ui.elements["growth-agent-preview-queue-status"].textContent, /Sign in/);
});
test("owner gets only reviewable candidates, with no approve/send action", async () => {
  const requests = [];
  const ui = setup(async (url, options) => {
    requests.push({url, options});
    return ok([
      { workflow_name: "<script>alert(1)</script>", status: "preview", requires_approval: true, is_synthetic_demo: true, dry_run: true },
      { workflow_name: "Completed", status: "completed", requires_approval: true },
      { workflow_name: "No approval needed", status: "preview", requires_approval: false }
    ]);
  }, "session-token");
  await ui.click();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/nova/growth-agent/workflows/review-queue?limit=50");
  assert.equal(requests[0].options.headers.Authorization, "Bearer session-token");
  assert.equal(requests[0].options.method, undefined);
  const children = ui.elements["growth-agent-preview-queue-list"].children;
  assert.equal(children.length, 1);
  assert.match(children[0].textContent, /DEMO/);
  assert.match(children[0].textContent, /<script>/);
  assert.match(ui.elements["growth-agent-preview-queue-status"].textContent, /No approvals or sends occurred/);
});
test("403 never renders review records", async () => {
  const ui = setup(async () => ({ ok: false, status: 403 }), "session-token");
  await ui.click();
  assert.equal(ui.elements["growth-agent-preview-queue-list"].children.length, 0);
  assert.match(ui.elements["growth-agent-preview-queue-status"].textContent, /Access denied/);
});
test("pending request cannot render after sign-out or org switch", async () => {
  let resolveResponse;
  const ui = setup(() => new Promise(resolve => { resolveResponse = resolve; }), "session-token");
  const pending = ui.click();
  ui.setOrg("owner-b");
  resolveResponse(ok([{ workflow_name: "Private", status: "preview", requires_approval: true }]));
  await pending;
  assert.equal(ui.elements["growth-agent-preview-queue-list"].children.length, 0);
  ui.signOut();
  assert.equal(ui.elements["growth-agent-preview-queue-list"].children.length, 0);
});
test("visible preview list clears when session changes after display", async () => {
  const ui = setup(async () => ok([
    {workflow_name: "Owner review", status: "awaiting_approval", requires_approval: true}
  ]), "session-token");
  await ui.click();
  assert.equal(ui.elements["growth-agent-preview-queue-list"].children.length, 1);
  ui.setToken("new-session-token");
  ui.listeners.focus();
  assert.equal(ui.elements["growth-agent-preview-queue-list"].children.length, 0);
});
