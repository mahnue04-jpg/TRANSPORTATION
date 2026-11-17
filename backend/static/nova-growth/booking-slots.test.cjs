const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "booking-slots.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const growth = fs.readFileSync(path.join(__dirname, "growth.js"), "utf8");

function load() {
  const window = {};
  const Option = function Option(label, value) { this.text = label; this.value = value; };
  vm.runInNewContext(source, { window, Option, Intl, Date, Set });
  return window.NovaBookingSlots;
}
function choice() {
  return {
    options: [],
    value: "old",
    replaceChildren(...items) { this.options = items; },
    add(item) { this.options.push(item); }
  };
}

test("rejects dates without timezone, malformed slots, and arbitrary strings", () => {
  const api = load();
  assert.equal(api.validSlot("2026-11-19T09:30:00Z"), true);
  assert.equal(api.validSlot("2026-11-19T09:30:00-06:00"), true);
  for (const v of ["2026-11-19 09:30", "2026-11-19T09:30:00", "yesterday", null, "2026-99-99T99:99:99Z"]) {
    assert.equal(api.validSlot(v), false);
  }
});

test("ignores unavailable/malformed slot rows and deduplicates valid times", () => {
  const api = load();
  const slots = api.availableSlots({ slots: [
    { starts_at_utc: "2026-11-19T18:00:00Z", available: true },
    { starts_at_utc: "2026-11-19T16:00:00Z" },
    { starts_at_utc: "2026-11-19T18:00:00Z" },
    { starts_at_utc: "2026-11-19T17:00:00Z", available: false },
    { starts_at_utc: "unknown" }, null
  ]});
  assert.deepEqual(Array.from(slots), ["2026-11-19T16:00:00Z", "2026-11-19T18:00:00Z"]);
});

test("select dropdown starts unselected and labels times in user timezone", () => {
  const api = load();
  const select = choice();
  assert.equal(api.populate(select, { slots: [{ starts_at_utc: "2026-11-19T18:00:00Z" }] }), 1);
  assert.equal(select.value, "");
  assert.match(select.options[1].text, /Nov.*19.*2026/);
  assert.equal(select.options[1].value, "2026-11-19T18:00:00Z");
  assert.equal(api.populate(select, { slots: [] }), 0);
  assert.equal(select.options.length, 1);
});

test("staging booking form prevents arbitrary timestamp editing and stale selection", () => {
  assert.match(html, /id="book-day" type="date"/);
  assert.match(html, /id="book-slot-choice"/);
  assert.match(html, /id="book-start"[^>]*readonly/);
  assert.match(html, /Staging appointment practice only/);
  assert.match(growth, /if \(!selected \|\| !availableTimes\.includes\(selected\)/);
  assert.match(growth, /key !== fetchedSlotKey/);
  assert.match(growth, /request !== slotRequest/);
});
