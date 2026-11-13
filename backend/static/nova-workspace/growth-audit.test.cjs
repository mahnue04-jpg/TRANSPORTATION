"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "growth-audit.js"), "utf8");
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve)); };

function setup(fetchImpl, initialToken = "", initialOrg = "org-a") {
  let token = initialToken;
  let org = initialOrg;
  const listeners = {};
  const documentListeners = {};
  const makeElement = () => ({
    textContent: "", disabled: false, children: [], events: {},
    addEventListener(type, fn) { this.events[type] = fn; },
    replaceChildren(...items) { this.children = items; },
    append(...items) { this.children.push(...items); }
  });
  const elements = Object.fromEntries([
    "growth-agent-audit-load", "growth-agent-audit-status",
    "growth-agent-audit-list", "sign-out"
  ].map(id => [id, makeElement()]));
  const window = {
    AmiCorSession: {
      getAccessToken: () => token,
      getOrganizationId: () => org,
      getAuthHeaders: () => ({ Authorization: "Bearer " + token })
    },
    addEventListener(type, fn) { listeners[type] = fn; }
  };
  const document = {
    getElementById(id) { return elements[id] || null; },
    createElement() { return makeElement(); },
    addEventListener(type, fn) { documentListeners[type] = fn; }
  };
  let callCount = 0;
  const fetch = (...args) => { callCount++; return fetchImpl(...args); };
  vm.runInNewContext(source, { window, document, fetch, console }, { filename: "growth-audit.js" });
  return {
    elements, listeners, documentListeners, getCallCount: () => callCount,
    setToken(value) { token = value; }, setOrg(value) { org = value; },
    click() { return elements["growth-agent-audit-load"].events.click(); },
    signOut() { return elements["sign-out"].events.click(); }
  };
}
const ok = events => ({ ok: true, status: 200, json: async () => ({ events }) });

test("signed-out owner does not request audit history", async () => {
  const ui = setup(() => { throw Error("Unauthorized fetch"); });
  await ui.click();
  assert.equal(ui.getCallCount(), 0);
  assert.match(ui.elements["growth-agent-audit-status"].textContent, /Sign in/);
  assert.equal(ui.elements["growth-agent-audit-list"].children.length, 0);
});

test("authenticated owner sees workflow events only, with no unsafe HTML interpolation", async () => {
  const requests = [];
  const ui = setup(async (url, opts) => {
    requests.push({ url, opts });
    return ok([
      { action: "workflow.preview", summary: "<img src=x onerror=alert(1)>" },
      { action: "contact.created", summary: "Not a workflow event" },
      { action: "workflow.execute", summary: "Mock workflow attempted" }
    ]);
  }, "token-a");
  await ui.click();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/nova/growth-agent/audit?limit=50");
  assert.equal(requests[0].opts.headers.Authorization, "Bearer token-a");
  assert.equal(requests[0].opts.cache, "no-store");
  assert.equal(ui.elements["growth-agent-audit-list"].children.length, 2);
  assert.match(ui.elements["growth-agent-audit-list"].children[0].textContent, /^workflow.preview/);
  assert.match(ui.elements["growth-agent-audit-list"].children[0].textContent, /<img src=x/);
  assert.match(ui.elements["growth-agent-audit-status"].textContent, /not prove external delivery/);
});

test("access-denied responses never render activity", async () => {
  const ui = setup(async () => ({ ok: false, status: 403 }), "token-a");
  await ui.click();
  assert.equal(ui.elements["growth-agent-audit-list"].children.length, 0);
  assert.match(ui.elements["growth-agent-audit-status"].textContent, /Access denied/);
});

test("sign-out while a request is pending suppresses stale history", async () => {
  let respond;
  const ui = setup(() => new Promise(resolve => { respond = resolve; }), "token-a");
  const operation = ui.click();
  ui.signOut();
  ui.setToken("");
  respond(ok([{ action: "workflow.execute", summary: "Private data" }]));
  await operation;
  assert.equal(ui.elements["growth-agent-audit-list"].children.length, 0);
  assert.match(ui.elements["growth-agent-audit-status"].textContent, /Sign in/);
});

test("switching organization while request is pending never displays other tenant events", async () => {
  let respond;
  const ui = setup(() => new Promise(resolve => { respond = resolve; }), "token-a", "org-a");
  const operation = ui.click();
  ui.setOrg("org-b");
  respond(ok([{ action: "workflow.preview", summary: "Wrong tenant" }]));
  await operation;
  assert.equal(ui.elements["growth-agent-audit-list"].children.length, 0);
});


test("already visible tenant history clears on focus after owner switches organization", async () => {
  const ui = setup(async () => ok([{action:"workflow.preview", summary:"Org A only"}]), "token-a", "org-a");
  await ui.click();
  assert.equal(ui.elements["growth-agent-audit-list"].children.length, 1);
  ui.setOrg("org-b");
  ui.listeners.focus();
  assert.equal(ui.elements["growth-agent-audit-list"].children.length, 0);
  assert.match(ui.elements["growth-agent-audit-status"].textContent, /organization changed/);
});

test("already visible history clears after identity change on tab visibility", async () => {
  const ui = setup(async () => ok([{action:"workflow.preview", summary:"Private"}]), "token-a", "org-a");
  await ui.click();
  assert.equal(ui.elements["growth-agent-audit-list"].children.length, 1);
  ui.setToken("token-b");
  ui.documentListeners.visibilitychange();
  assert.equal(ui.elements["growth-agent-audit-list"].children.length, 0);
});
