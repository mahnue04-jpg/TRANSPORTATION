"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { report } = require("./demo-report.js");

const base = () => ({
  label: "SYNTHETIC DEMO — not live customers",
  demo_mode_flag: true,
  profile: { is_synthetic_demo: true },
  chat: { first: { grounded: true, ai_disclosed: true }, duplicate_contact_reused: true },
  crm_edit: { lead_state: "qualified" },
  booking: { status: "confirmed" },
  cancel_rebook: { cancelled_status: "cancelled", reused_same_row: true },
  reschedule: { status: "rescheduled" },
  reminder_workflow: { status: "completed", dry_run: true },
  restart_recovery: { recovered_count: 1, live_send: false },
  handoff: { status: "handed_off" },
  marketing_suppressed: { status: "suppressed", stop_reason: "CONSENT_REQUIRED", live_send: false },
  double_book_blocked: "DOUBLE_BOOK"
});

test("actual route-wrapped synthetic demo renders evidence, never live claims", () => {
  const result = report(base());
  assert.equal(result.title, "Synthetic customer journey — owner review");
  assert.equal(result.live, false);
  assert.equal(result.rows.filter(row => row.state === "passed").length, 11);
  assert.equal(result.rows.filter(row => row.state === "not connected").length, 3);
  assert.ok(result.note.includes("Fictional data only"));
});

test("a profile flag without server demo-mode confirmation fails closed", () => {
  const b = base();
  delete b.demo_mode_flag;
  assert.equal(report(b).title, "Demonstration not verified");
});

test("server demo flag without synthetic profile fails closed", () => {
  const b = base();
  b.profile.is_synthetic_demo = false;
  assert.equal(report(b).title, "Demonstration not verified");
});

test("unlabeled, malformed and former top-level spoofing fail closed", () => {
  const b = base();
  b.label = "real customers";
  assert.equal(report(b).title, "Demonstration not verified");
  assert.equal(report({ is_synthetic_demo: true }).title, "Demonstration not verified");
  assert.equal(report(null).title, "Demonstration not verified");
  assert.equal(report([]).title, "Demonstration not verified");
});

test("unproven steps remain not verified even in a confirmed synthetic demo", () => {
  const b = base();
  delete b.chat;
  delete b.booking;
  delete b.reminder_workflow;
  const result = report(b);
  assert.equal(result.live, false);
  assert.equal(result.rows.find(r => r.label === "FAQ chat").state, "not verified");
  assert.equal(result.rows.find(r => r.label === "Appointment booking").state, "not verified");
  assert.equal(result.rows.find(r => r.label === "Reminder dry run").state, "not verified");
});
