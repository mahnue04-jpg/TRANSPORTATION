const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");

test("receptionist explains the real-call restriction without developer callback details", () => {
  assert.match(html, /Real phone calls are not active/);
  assert.match(html, /Connect your business calendar before accepting real appointments/);
  assert.doesNotMatch(html, /calendar_oauth=1&amp;state/);
});
test("website setup describes connection in business language", () => {
  assert.match(html, /Create a website connection for Nova Chat/);
  assert.match(html, /Visitors must agree before their contact details are saved/);
  assert.doesNotMatch(html, /Signed installation token scoped to domain/);
});
test("advanced configuration keeps original form ids and labels intent", () => {
  for (const id of ["biz-hours", "biz-services", "biz-faqs"]) {
    assert.match(html, new RegExp('id="' + id + '"'));
  }
  assert.match(html, /Common customer questions \(advanced setup format\)/);
});
