"use strict";
// Source-level integration guard for the owner bookkeeping console.
// This verifies DOM/API contracts and the absence of customer-delivery calls;
// real signed-in browser testing is still required in isolated staging.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "static/nova-work/index.html"), "utf8");
const js = fs.readFileSync(path.join(root, "static/nova-work/bookkeeping.js"), "utf8");

test("Work & Revenue renders owner review console and its script", () => {
  assert.match(html, /id="nova-bookkeeping-console"/);
  assert.match(html, /src="\/static\/nova-work\/bookkeeping\.js"/);
  const ids = [
    "bookkeeping-load-queue", "bookkeeping-message", "bookkeeping-next-action",
    "bookkeeping-job-select", "bookkeeping-status", "bookkeeping-download",
    "bookkeeping-approve", "bookkeeping-reject", "bookkeeping-recover",
    "bookkeeping-submit-form", "bookkeeping-submit-button", "bookkeeping-kind",
    "bookkeeping-as-of", "bookkeeping-file", "bookkeeping-engagement",
    "bookkeeping-task", "bookkeeping-load-tasks", "bookkeeping-eligible-tasks"
  ];
  for (const id of ids) {
    assert.match(html, new RegExp('id="' + id + '"'));
    assert.ok(js.includes('"' + id + '"'), id + " must be used by console controller");
  }
});

test("Review requests use authenticated owner-only bookkeeping routes", () => {
  assert.match(js, /\/api\/nova\/work\/operations\/durable\/bookkeeping/);
  for (const route of [
    "/review-queue?limit=50", "/jobs/", "/download", "/review",
    "/recover", "/engagements/", "/tasks/"
  ]) assert.ok(js.includes(route), route + " route is required");
  assert.match(js, /getAuthHeaders/);
  assert.match(js, /\/eligible-tasks/);
  assert.match(js, /selectedTask/);
  assert.match(html, /id="bookkeeping-task"[^>]+readonly/);
  assert.match(html, /id="bookkeeping-engagement"[^>]+readonly/);
  assert.match(js, /credentials: "same-origin"/);
  assert.match(js, /cache: "no-store"/);
  assert.match(js, /status !== "AWAITING_REVIEW"/);
  assert.match(js, /status !== "PROCESSING"/);
});

test("Does not claim client delivery, financial execution, or approval as a contract", () => {
  assert.match(html, /No automatic file transmission|never sends work to a client/);
  assert.match(js, /Nothing delivered/);
  assert.doesNotMatch(js, /\/payments\/execute|\/contracts\/accept|\/customers\/send/);
  assert.match(html, /server verifies scope/i);
  assert.match(js, /crypto\.randomUUID/);
});

test("Input is bounded and work type allowlisted", () => {
  assert.match(js, /file\.size > 1000000/);
  for (const workType of [
    "transaction_workpaper", "receivables_aging", "payables_aging"
  ]) {
    assert.ok(js.includes(workType));
    assert.ok(html.includes('value="' + workType + '"'));
  }
});
