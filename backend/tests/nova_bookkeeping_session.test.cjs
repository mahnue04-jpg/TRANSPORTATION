"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const script = fs.readFileSync(path.join(__dirname, "../static/nova-work/bookkeeping.js"), "utf8");

function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return {promise, resolve};
}
function harness() {
  const ids = [
    "nova-bookkeeping-console", "bookkeeping-message", "bookkeeping-next-action",
    "bookkeeping-job-select", "bookkeeping-load-queue", "bookkeeping-status",
    "bookkeeping-download", "bookkeeping-approve", "bookkeeping-reject",
    "bookkeeping-recover", "bookkeeping-submit-form", "bookkeeping-submit-button",
    "bookkeeping-load-tasks", "bookkeeping-eligible-tasks", "bookkeeping-kind",
    "bookkeeping-as-of", "bookkeeping-file", "bookkeeping-engagement", "bookkeeping-task"
  ];
  const nodes = new Map(ids.map(id => [id, {
    value: "", textContent: "", disabled: false, required: false, files: [],
    listeners: {}, options: [],
    addEventListener(name, callback) { this.listeners[name] = callback; },
    replaceChildren(...items) { this.options = items; this.value = ""; },
    appendChild(option) { this.options.push(option); },
    querySelector() { return null; }
  }]));
  let token = "Bearer synthetic-owner-a";
  const replies = [];
  const windowEvents = {};
  let downloads = 0;
  const context = {
    document: {
      getElementById(id) { return nodes.get(id) || null; },
      addEventListener() {},
      body: {appendChild() {}},
      createElement() { return {click() {downloads++;}, remove() {}}; }
    },
    window: {
      AmiCorSession: {getAuthHeaders() {
        return token ? {Authorization: token} : {};
      }},
      addEventListener(name, callback) {windowEvents[name] = callback;},
      crypto: {randomUUID() {return "synthetic-id";}},
      setTimeout() {}
    },
    Option: class Option {
      constructor(text, value) { this.text = text; this.value = value; }
    },
    URL: {createObjectURL() {return "blob:synthetic";}, revokeObjectURL() {}},
    fetch(url) {
      const entry = deferred();
      replies.push({url, entry});
      return entry.promise;
    }
  };
  vm.runInNewContext(script, context, {filename: "bookkeeping.js"});
  return {nodes, replies, windowEvents, getDownloadCount() {return downloads;}, setToken(value) {token = value;}};
}
async function settle() {
  for (let n = 0; n < 12; n++) await Promise.resolve();
}

test("changing owners while review queue fetch is pending cannot display first owner's jobs", async () => {
  const h = harness();
  h.nodes.get("bookkeeping-load-queue").listeners.click();
  assert.equal(h.replies.length, 1);
  h.setToken("Bearer synthetic-owner-b");
  h.windowEvents.focus();
  h.replies[0].entry.resolve({
    ok: true, json: async () => ({jobs: [{
      job_id: "synthetic-owner-a-job", task_id: "private-a",
      work_type: "receivables_aging", status: "AWAITING_REVIEW"
    }]})
  });
  await settle();
  const select = h.nodes.get("bookkeeping-job-select");
  assert.equal(select.options.length, 1);
  assert.doesNotMatch(select.options[0].text, /private-a/);
  assert.match(h.nodes.get("bookkeeping-message").textContent, /session changed/i);
});

test("logging out before eligible assignment response hides formerly authorized task", async () => {
  const h = harness();
  h.nodes.get("bookkeeping-load-tasks").listeners.click();
  assert.equal(h.replies.length, 1);
  h.setToken("");
  h.windowEvents.focus();
  h.replies[0].entry.resolve({
    ok: true, json: async () => ({tasks: [{
      task_id: "confidential-a", engagement_id: "engagement-a",
      work_type: "payables_aging"
    }]})
  });
  await settle();
  assert.equal(h.nodes.get("bookkeeping-eligible-tasks").options.length, 1);
  assert.equal(h.nodes.get("bookkeeping-engagement").value, "");
  assert.equal(h.nodes.get("bookkeeping-task").value, "");
});

test("no bookkeeping fetch is sent without a signed-in owner", async () => {
  const h = harness();
  h.setToken("");
  h.windowEvents.focus();
  h.nodes.get("bookkeeping-load-queue").listeners.click();
  await settle();
  assert.equal(h.replies.length, 0);
  assert.match(h.nodes.get("bookkeeping-message").textContent, /sign-in required/i);
});


test("download response from previous owner never creates a local financial file", async () => {
  const h = harness();
  h.nodes.get("bookkeeping-load-queue").listeners.click();
  h.replies[0].entry.resolve({
    ok: true, json: async () => ({jobs: [{
      job_id: "sensitive-owner-a-job", task_id: "task-a",
      work_type: "payables_aging", status: "AWAITING_REVIEW"
    }]})
  });
  await settle();
  const chooser = h.nodes.get("bookkeeping-job-select");
  chooser.value = "0";
  chooser.listeners.change();
  h.nodes.get("bookkeeping-download").listeners.click();
  assert.equal(h.replies.length, 2);
  const body = deferred();
  h.replies[1].entry.resolve({ok: true, blob: () => body.promise});
  await settle();
  h.setToken("Bearer synthetic-owner-b");
  h.windowEvents.focus();
  body.resolve({size: 20});
  await settle();
  assert.equal(h.getDownloadCount(), 0);
  assert.equal(h.nodes.get("bookkeeping-job-select").options.length, 1);
  assert.match(h.nodes.get("bookkeeping-message").textContent, /session changed/i);
});
