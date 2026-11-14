"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const root = __dirname;
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const js = fs.readFileSync(path.join(root, "growth-readonly.js"), "utf8");

test("Growth status is explicitly read-only, manual and discoverable", () => {
  assert.match(html, /id="growth-readonly-refresh"/);
  assert.match(html, /id="growth-readonly-result"/);
  assert.match(html, /growth-readonly\.js/);
  assert.match(js, /addEventListener\("click"/);
  assert.match(js, /method: "GET"/);
  assert.doesNotMatch(js, /method:\s*"(POST|PATCH|DELETE|PUT)"/);
});
test("UI does not claim unimplemented approvals or handoff", () => {
  assert.match(js, /Owner approvals and Operations handoff: not connected/);
  assert.match(js, /not proof of live delivery/);
  assert.match(js, /Unexpected API format/);
  assert.match(js, /Access denied/);
  assert.match(js, /Leads returned \(not a total\)/);
  assert.match(js, /Conversations returned \(not a total\)/);
  assert.match(js, /Appointments returned \(maximum 50, not a total\)/);
  assert.doesNotMatch(js, /fetchReadOnly\\("(leads|conversations|appointments)"/);
});

function harness({ token = "test-token", responseByPath = {}, failFetch = false } = {}) {
  let click;
  const requests = [];
  const trigger = {
    disabled: false,
    addEventListener(name, handler) { if (name === "click") click = handler; }
  };
  const result = { textContent: "" };
  const session = {
    getAccessToken() { return token; },
    getAuthHeaders() { return { Authorization: "Bearer " + token }; }
  };
  const document = {
    getElementById(id) {
      return id === "growth-readonly-refresh" ? trigger :
        id === "growth-readonly-result" ? result : null;
    }
  };
  const fetch = async (url, options) => {
    requests.push({ url, options });
    if (failFetch) throw new Error("offline");
    const suffix = url.split("/").at(-1);
    const item = responseByPath[suffix] || {};
    const status = item.status || 200;
    return {
      status, ok: status >= 200 && status < 300,
      json: async () => item.body || {}
    };
  };
  vm.runInNewContext(js, { document, window: { AmiCorSession: session }, fetch });
  return { trigger, result, requests, click: () => click() };
}

test("unsigned session causes no network calls", async () => {
  const h = harness({ token: "" });
  await h.click();
  assert.equal(h.requests.length, 0);
  assert.match(h.result.textContent, /Sign in/);
});

test("successful click uses only authenticated GETs and honest returned counts", async () => {
  const h = harness({ responseByPath: {
    health: { body: { status: "ok" } },
    counts: { body: { counts: { leads: 205, conversations: 103, appointments: 52 } } }
  } });
  await h.click();
  assert.equal(h.requests.length, 2);
  for (const request of h.requests) {
    assert.equal(request.options.method, "GET");
    assert.equal(request.options.headers.Authorization, "Bearer test-token");
    assert.match(request.url, /^\/api\/nova\/growth-agent\//);
  }
  assert.match(h.result.textContent, /Leads returned \(not a total\): 1/);
  assert.match(h.result.textContent, /Owner approvals and Operations handoff: not connected/);
  assert.doesNotMatch(h.result.textContent, /private@example.invalid/);
  assert.equal(h.trigger.disabled, false);
});

test("permission denial and malformed API responses fail closed", async () => {
  for (const responseByPath of [
    { counts: { status: 403 } },
    { counts: { body: { counts: { leads: null, conversations: 0, appointments: 0 } } } }
  ]) {
    const h = harness({ responseByPath });
    await h.click();
    assert.match(h.result.textContent, /unavailable for this review/i);
    assert.doesNotMatch(h.result.textContent, /Total leads/);
    assert.equal(h.trigger.disabled, false);
  }
});

test("network failure is displayed without claiming an action", async () => {
  const h = harness({ failFetch: true });
  await h.click();
  assert.match(h.result.textContent, /No actions were taken/);
  assert.equal(h.trigger.disabled, false);
});

test("expired session, disabled feature, and server error show distinct safe messages", async () => {
  for (const [status, expected] of [
    [401, /Session expired/],
    [404, /disabled or unavailable/],
    [503, /request failed \(503\)/]
  ]) {
    const h = harness({ responseByPath: { health: { status } } });
    await h.click();
    assert.match(h.result.textContent, expected);
    assert.doesNotMatch(h.result.textContent, /Leads returned/);
    assert.equal(h.trigger.disabled, false);
  }
});

test("repeated manual refresh remains read-only and available", async () => {
  const h = harness({ responseByPath: {
    health: { body: { status: "ok" } },
    counts: { body: { counts: { leads: 0, conversations: 0, appointments: 0 } } }
  } });
  // Both checks should succeed without invoking any write request.
  await h.click();
  assert.match(h.result.textContent, /Leads returned \(not a total\): 0/);
  await h.click();
  assert.equal(h.requests.length, 4);
  assert.equal(h.trigger.disabled, false);
});
