const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const src = fs.readFileSync(path.join(__dirname, "growth.js"), "utf8");

test("test booking shortcut appears only for explicitly synthetic CRM leads", () => {
  assert.match(src, /l\.is_synthetic_demo \? ' <button type="button" class="secondary" data-test-booking>/);
  assert.match(src, /querySelectorAll\("\[data-test-booking\]"\)/);
  assert.match(src, /const id = row\?\.dataset\.leadId/);
  assert.match(src, /\$\("wf-contact"\)\.value = id/);
});

test("shortcut does not book, mutate a lead, or enable an external provider", () => {
  const shortcut = src.split('box.querySelectorAll("[data-test-booking]")')[1]
    .split('box.querySelectorAll("[data-save-lead]")')[0];
  assert.doesNotMatch(shortcut, /await api|fetch\(|appointments|calendar|POST|PATCH|provider/);
  assert.match(shortcut, /if \(!id\) return/);
});
