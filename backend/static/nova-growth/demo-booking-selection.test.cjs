const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const script = fs.readFileSync(path.join(__dirname, "growth.js"), "utf8");

test("synthetic contacts alone get the staging booking button", () => {
  assert.match(script, /l\.is_synthetic_demo \? ' <button type="button" class="secondary" data-test-booking>/);
  assert.match(script, /querySelectorAll\("\[data-test-booking\]"\)/);
});
test("booking selection copies the existing CRM record id, not the name", () => {
  assert.match(script, /const id = row\?\.dataset\.leadId/);
  assert.match(script, /\$\("wf-contact"\)\.value = id/);
  assert.match(script, /Demo customer selected for staging booking/);
});
test("selection does not create appointments or change the CRM record", () => {
  const block = script.split('box.querySelectorAll("[data-test-booking]")')[1].split('box.querySelectorAll("[data-save-lead]")')[0];
  assert.doesNotMatch(block, /await api\(|fetch\(|method: "POST"|method: "PATCH"/);
});
