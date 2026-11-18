/* Human-readable, evidence-limited owner report for fictional Growth demo.
   No live integrations, private contact data, or unsupported success claims. */
(function (root) {
  "use strict";

  function record(label, state, detail) {
    return { label, state, detail };
  }

  // Backend stores the flag on profile and the HTTP handler adds demo_mode_flag.
  function confirmedSyntheticDemo(data) {
    if (!data || typeof data !== "object") return false;
    if (data.is_synthetic_demo === true || data.demo_mode_flag === true) return true;
    const profile = data.profile;
    return !!(profile && typeof profile === "object" && profile.is_synthetic_demo === true);
  }

  function report(data) {
    if (!confirmedSyntheticDemo(data)) {
      return {
        title: "Demonstration not verified",
        rows: [record("Synthetic demonstration", "not verified", "No confirmed synthetic demo result was returned.")],
        live: false,
      };
    }
    const rows = [];
    const chat = data.chat && data.chat.first;
    rows.push(record("FAQ chat", chat && chat.grounded === true && chat.ai_disclosed === true ? "passed" : "not verified",
      "Grounded answer and AI disclosure in the fictional scenario"));
    rows.push(record("Duplicate contact protection", data.chat && data.chat.duplicate_contact_reused === true ? "passed" : "not verified",
      "Existing fictional contact reused instead of creating another"));
    rows.push(record("CRM lead update", data.crm_edit && data.crm_edit.lead_state === "qualified" ? "passed" : "not verified",
      "Synthetic lead marked qualified"));
    rows.push(record("Appointment booking", data.booking && data.booking.status === "confirmed" ? "passed" : "not verified",
      "Internal booking only — external calendar confirmation not established"));
    rows.push(record("Cancel and rebook", data.cancel_rebook &&
      data.cancel_rebook.cancelled_status === "cancelled" &&
      data.cancel_rebook.reused_same_row === true ? "passed" : "not verified",
      "Fictional cancelled slot reused"));
    rows.push(record("Rescheduling", data.reschedule && data.reschedule.status === "rescheduled" ? "passed" : "not verified",
      "Internal reschedule; not externally confirmed"));
    rows.push(record("Reminder dry run", data.reminder_workflow &&
      data.reminder_workflow.status === "completed" &&
      data.reminder_workflow.dry_run === true ? "passed" : "not verified",
      "Mock delivery — no inbox receipt confirmed"));
    rows.push(record("Pending-job recovery", data.restart_recovery &&
      Number.isInteger(data.restart_recovery.recovered_count) &&
      data.restart_recovery.recovered_count > 0 &&
      data.restart_recovery.live_send === false ? "passed" : "not verified",
      "Mock queued work recovered in a dry run"));
    rows.push(record("Human handoff", data.handoff &&
      data.handoff.status === "handed_off" ? "passed" : "not verified",
      "Conversation handed to human handler"));
    rows.push(record("Marketing consent protection", data.marketing_suppressed &&
      data.marketing_suppressed.status === "suppressed" &&
      data.marketing_suppressed.stop_reason === "CONSENT_REQUIRED" &&
      data.marketing_suppressed.live_send === false ? "passed" : "not verified",
      "Marketing workflow suppressed when required consent was absent"));
    rows.push(record("Double-booking prevention",
      data.double_book_blocked === "DOUBLE_BOOK" ? "passed" : "not verified",
      "Duplicate slot rejected in fictional workflow"));

    // These gates must NEVER pass based on synthetic fixtures.
    rows.push(record("Real calendar synchronization", "not connected", "No externally confirmed booking shown"));
    rows.push(record("Real customer email/SMS", "not connected", "Mock provider results do not prove delivery"));
    rows.push(record("Paid customer revenue", "not connected", "No billed transaction or verified attribution"));
    const pass = rows.filter((row) => row.state === "passed").length;
    return {
      title: "Synthetic customer journey — owner review",
      note: "Fictional data only. Passing checks are not evidence of live service or paid customers.",
      pass,
      total: rows.length,
      rows,
      live: false,
    };
  }

  const api = { report };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.NovaGrowthDemoReport = api;
})(typeof window !== "undefined" ? window : null);
