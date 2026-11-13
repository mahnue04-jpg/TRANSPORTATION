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
    replaceChildren(...items) { this.children = items; },
    appendChild(item) { this.children.push(item); }
  }; }
  const elements = Object.fromEntries([
    "growth-agent-preview-queue-load", "growth-agent-preview-queue-status",
    "growth-agent-preview-queue-list", "growth-agent-preview-detail",
    "growth-agent-preview-detail-status", "growth-agent-preview-detail-steps",
    "growth-agent-preview-decision-controls", "growth-agent-preview-reject",
    "growth-agent-preview-request-information", "sign-out"
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
      { run_id: "run-demo-1", workflow_name: "<script>alert(1)</script>", status: "preview", requires_approval: true, is_synthetic_demo: true, dry_run: true },
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


test("owner can view redacted workflow details without posting or executing", async () => {
  const requests = [];
  const ui = setup(async (url, opts) => {
    requests.push({ url, opts });
    if (url.endsWith("/review-queue?limit=50")) return ok([
      {run_id: "run-1", workflow_name: "Inquiry acknowledgment", status: "preview", requires_approval: true, is_synthetic_demo: true, dry_run: true}
    ]);
    if (url.endsWith("/review-queue/run-1")) return {
      ok: true, status: 200, json: async () => ({
        run_id: "run-1", workflow_name: "Inquiry acknowledgment", status: "preview",
        requires_approval: true, content_redacted: true, is_synthetic_demo: true,
        steps: [{channel: "email", scheduled_for_utc: "2026-11-13T18:00:00Z", quiet_hours_adjusted: false}]
      })
    };
    throw Error("Unexpected fetch");
  }, "session-token");
  await ui.click();
  const item = ui.elements["growth-agent-preview-queue-list"].children[0];
  assert.equal(item.children.length, 1);
  await item.children[0].listeners.click();
  assert.equal(requests.length, 2);
  assert.ok(requests.every(entry => entry.opts.method === undefined));
  assert.equal(ui.elements["growth-agent-preview-detail-steps"].children.length, 1);
  assert.match(ui.elements["growth-agent-preview-detail-status"].textContent, /Nothing approved or sent/);
});

test("unredacted or mismatched workflow detail responses are rejected", async () => {
  const ui = setup(async url => {
    if (url.endsWith("?limit=50")) return ok([
      {run_id:"run-1", workflow_name:"Example", status:"preview", requires_approval:true}
    ]);
    return {ok:true,status:200,json:async()=>({
      run_id:"other-run", status:"preview", requires_approval:true,
      content_redacted:false, steps:[{channel:"email"}]
    })};
  }, "session-token");
  await ui.click();
  await ui.elements["growth-agent-preview-queue-list"].children[0].children[0].listeners.click();
  assert.equal(ui.elements["growth-agent-preview-detail-steps"].children.length, 0);
  assert.match(ui.elements["growth-agent-preview-detail-status"].textContent, /Unexpected or stale/);
});

test("Reject requires two owner clicks and never executes a workflow", async () => {
  const requests = [];
  const ui = setup(async (url, opts) => {
    requests.push({url, opts});
    if (url.endsWith("?limit=50")) return ok([
      {run_id:"reject-run", workflow_name:"Review", status:"preview", requires_approval:true}
    ]);
    if (url.endsWith("/reject-run")) return {
      ok:true, status:200, json:async()=>({
        run_id:"reject-run", workflow_name:"Review", status:"preview",
        requires_approval:true, content_redacted:true, steps:[]
      })
    };
    if (url.endsWith("/reject-run/decision")) return {
      ok:true, status:200, json:async()=>({
        run_id:"reject-run", status:"cancelled", decision:"reject",
        execution_performed:false, live_send:false
      })
    };
    throw Error("Unexpected URL");
  }, "session-token");
  await ui.click();
  await ui.elements["growth-agent-preview-queue-list"].children[0].children[0].listeners.click();
  const reject = ui.elements["growth-agent-preview-reject"];
  await reject.listeners.click();
  assert.equal(requests.length, 2, "first click is confirmation only");
  assert.match(reject.textContent, /Confirm reject/);
  await reject.listeners.click();
  assert.equal(requests.length, 3);
  assert.equal(requests[2].opts.method, "POST");
  assert.deepEqual(JSON.parse(requests[2].opts.body), {decision:"reject"});
  assert.match(ui.elements["growth-agent-preview-queue-status"].textContent, /Owner decision recorded/);
  assert.equal(ui.elements["growth-agent-preview-queue-list"].children.length, 0);
});

test("Request information uses non-executing decision endpoint and stays tenant scoped", async () => {
  const requests = [];
  const ui = setup(async (url, opts) => {
    requests.push({url,opts});
    if (url.endsWith("?limit=50")) return ok([
      {run_id:"info-run", workflow_name:"Review", status:"preview", requires_approval:true}
    ]);
    if (url.endsWith("/info-run")) return {
      ok:true, status:200, json:async()=>({
        run_id:"info-run", workflow_name:"Review", status:"preview",
        requires_approval:true, content_redacted:true, steps:[]
      })
    };
    if (url.endsWith("/info-run/decision")) return {
      ok:true,status:200,json:async()=>({
        run_id:"info-run", status:"needs_information",decision:"request_information",
        execution_performed:false, live_send:false
      })
    };
    throw Error("Unexpected URL");
  }, "session-token");
  await ui.click();
  await ui.elements["growth-agent-preview-queue-list"].children[0].children[0].listeners.click();
  const info = ui.elements["growth-agent-preview-request-information"];
  await info.listeners.click();
  assert.equal(requests.length, 2);
  await info.listeners.click();
  assert.equal(requests.length, 3);
  assert.deepEqual(JSON.parse(requests[2].opts.body), {decision:"request_information"});
  assert.match(ui.elements["growth-agent-preview-queue-status"].textContent, /On hold — information needed/);
});

test("changed organization blocks owner decision before POST", async () => {
  const requests = [];
  const ui = setup(async (url, opts) => {
    requests.push({url, opts});
    if (url.endsWith("?limit=50")) return ok([
      {run_id:"run-1",workflow_name:"Review",status:"preview",requires_approval:true}
    ]);
    return {ok:true,status:200,json:async()=>({
      run_id:"run-1",status:"preview",requires_approval:true,content_redacted:true,steps:[]
    })};
  }, "session-token");
  await ui.click();
  await ui.elements["growth-agent-preview-queue-list"].children[0].children[0].listeners.click();
  ui.setOrg("other-org");
  await ui.elements["growth-agent-preview-reject"].listeners.click();
  assert.equal(requests.length, 2);
  assert.equal(ui.elements["growth-agent-preview-queue-list"].children.length, 0);
});


test("request-information decision reports hold rather than customer outreach", async () => {
  const ui = setup(async (url) => {
    if (url.endsWith("?limit=50")) return ok([{run_id:"hold-1",workflow_name:"Review",status:"preview",requires_approval:true}]);
    if (url.endsWith("/hold-1")) return {ok:true,status:200,json:async()=>({run_id:"hold-1",status:"preview",requires_approval:true,content_redacted:true,steps:[]})};
    return {ok:true,status:200,json:async()=>({run_id:"hold-1",status:"needs_information",decision:"request_information",execution_performed:false,live_send:false})};
  }, "session-token");
  await ui.click();
  await ui.elements["growth-agent-preview-queue-list"].children[0].children[0].listeners.click();
  const info = ui.elements["growth-agent-preview-request-information"];
  assert.match(info.textContent, /Place on hold/);
  await info.listeners.click();
  await info.listeners.click();
  const message = ui.elements["growth-agent-preview-queue-status"].textContent;
  assert.match(message, /On hold/);
  assert.match(message, /No workflow executed or message sent/);
  assert.doesNotMatch(message, /Information requested/);
});
