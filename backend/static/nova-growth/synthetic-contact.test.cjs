const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const js = fs.readFileSync(path.join(__dirname, "growth.js"), "utf8");

test("owner can prepare only a synthetic booking customer", () => {
  assert.match(html, /id="prepare-synthetic-contact"/);
  assert.match(js, /requireSession\(\)/);
  assert.match(js, /\/api\/nova\/growth-agent\/staging\/booking-contact/);
  assert.match(js, /if \(!data\.is_synthetic_demo \|\| !data\.staging_only \|\| !data\.contact_id\)/);
});

test("synthetic fixture loads CRM and fills Customer ID, no booking side effect", () => {
  const section = js.split('$("prepare-synthetic-contact").addEventListener')[1]
    .split('$("prepare-staging-service").addEventListener')[0];
  assert.match(section, /\$\("wf-contact"\)\.value = data\.contact_id/);
  assert.match(section, /await refreshLeads\(\)/);
  assert.doesNotMatch(section, /\/appointments"|\/widget\/chat|create-widget|book-slot/);
});

test("booked appointment is labeled synthetic only for selected test customer", () => {
  assert.match(js, /let selectedSyntheticContactId = ""/);
  assert.match(js, /selectedSyntheticContactId = data\.contact_id/);
  assert.match(js, /is_synthetic_demo: Boolean\(selectedSyntheticContactId\) && contactId === selectedSyntheticContactId/);
});
