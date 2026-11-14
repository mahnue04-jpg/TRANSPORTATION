"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
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
});
