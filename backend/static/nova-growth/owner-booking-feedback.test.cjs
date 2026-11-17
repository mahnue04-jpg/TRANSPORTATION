const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const js = fs.readFileSync(path.join(__dirname, "growth.js"), "utf8");

test("booking has readable status and technical details collapsed by default", () => {
  assert.match(html, /id="booking-result"[^>]*role="status"[^>]*aria-live="polite"[^>]*hidden/);
  assert.match(html, /<details id="booking-technical"/);
  assert.match(html, /<summary>Technical booking details<\/summary>/);
  assert.match(js, /bookingTechnical\.open = false/);
});

test("appointment lifecycle statuses receive plain-language results", () => {
  assert.match(js, /status === "confirmed"/);
  assert.match(js, /status === "rescheduled"/);
  assert.match(js, /status === "cancelled"/);
  assert.match(js, /timeZone: "America\/Chicago"/);
  assert.match(js, /Not confirmed on Google Calendar/);
  assert.match(js, /real notifications remain off/);
});

test("user-facing status derives from textContent, not HTML or client-side writes", () => {
  const start = js.indexOf("function localBookingTime(");
  const end = js.indexOf("const banner =", start);
  assert.ok(start !== -1 && end > start, "booking feedback helpers present");
  const portion = js.slice(start, end);
  assert.match(portion, /bookingSummary\.textContent = feedback\.text/);
  assert.doesNotMatch(portion, /innerHTML|fetch\(|api\(|method: "POST"/);
  assert.match(portion, /new MutationObserver\(refreshBookingFeedback\)/);
});
