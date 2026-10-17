"use strict";

(function () {
  function $(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function headers() {
    var result = { "Content-Type": "application/json" };
    if (session() && session().getAuthHeaders) Object.assign(result, session().getAuthHeaders());
    else if (token()) result.Authorization = "Bearer " + token();
    return result;
  }
  async function api(path, options) {
    var response = await fetch(path, Object.assign({}, options || {}, { headers: headers() }));
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (!response.ok) {
      var detail = body && typeof body.detail === "string" ? body.detail : "Request failed.";
      var error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return body;
  }
  function countChip(label, value) {
    return "<span>" + escapeHtml(label) + ": " + escapeHtml(value) + "</span>";
  }
  function reasons(items) {
    if (!items || !items.length) return "<li>No qualification reason stored yet.</li>";
    return items.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("");
  }
  function card(row) {
    var sent = row.actually_sent ? "Sent, with a receipt." : "Draft. This has not been sent.";
    var receipt = row.receipt_verified ? escapeHtml(row.receipt) : "No send receipt is stored.";
    var fetched = row.provenance_fetched_at ? escapeHtml(row.provenance_fetched_at) : "No source fetch time stored.";
    var blocker = row.blocker_reason ? escapeHtml(row.blocker_reason) : "No blocker stored.";
    var actions = "";
    if (row.application_id && (row.stage === "APPROVED_NOT_SENT" || row.stage === "BLOCKED")) {
      actions += "<button type=\"button\" data-first-client-action=\"attempt\" data-id=\"" +
        escapeHtml(row.application_id) + "\">Record blocked handoff</button>";
    }
    if (row.application_id && row.receipt_verified) {
      actions += "<label>Follow-up<input type=\"datetime-local\" data-follow-up-for=\"" +
        escapeHtml(row.application_id) + "\" /></label>" +
        "<button type=\"button\" data-first-client-action=\"follow-up\" data-id=\"" +
        escapeHtml(row.application_id) + "\">Save follow-up</button>" +
        "<button type=\"button\" data-first-client-action=\"ack\" data-id=\"" +
        escapeHtml(row.application_id) + "\">Record acknowledgement</button>";
    }
    if (row.application_id && row.actually_sent) {
      actions += "<button type=\"button\" data-first-client-action=\"failure\" data-id=\"" +
        escapeHtml(row.application_id) + "\">Record delivery failure</button>";
    }
    return "<article class=\"first-client-card\">" +
      "<h3>" + escapeHtml(row.title) + "</h3>" +
      "<p>" + escapeHtml(row.company_name) + " · " + escapeHtml(row.record_class) +
      " · " + escapeHtml(row.source || "source not stored") + "</p>" +
      "<p>Stage: " + escapeHtml(row.stage) + "</p>" +
      "<p>Sent vs draft: " + escapeHtml(sent) + "</p>" +
      "<p>Source URL: " + escapeHtml(row.source_url || "none stored") + "</p>" +
      "<p>Fetched at: " + fetched + " (" + escapeHtml(row.provenance_basis || "not stored") + ")</p>" +
      "<p>Blocker: " + blocker + "</p>" +
      "<p>Qualification: " + escapeHtml(row.qualification_outcome || "not qualified yet") + "</p>" +
      "<ul>" + reasons(row.qualification_reasons) + "</ul>" +
      "<p>Proposal preview: " + escapeHtml(row.proposal_preview || "No proposal draft yet.") + "</p>" +
      "<p>Receipt: " + receipt + "</p>" +
      "<p>Next action: " + escapeHtml(row.next_action) + "</p>" +
      "<div class=\"first-client-actions\">" + actions + "</div>" +
      "<p class=\"first-client-note\" id=\"first-client-note-" + escapeHtml(row.application_id || row.opportunity_id) + "\"></p>" +
      "</article>";
  }
  function render(board) {
    var counts = board.counts || {};
    if ($("first-client-counts")) {
      $("first-client-counts").innerHTML =
        countChip("Top matches", counts.top_matches || 0) +
        countChip("Drafts", counts.drafts || 0) +
        countChip("Approved, not sent", counts.approved_not_sent || 0) +
        countChip("Actually sent", counts.actually_sent || 0) +
        countChip("Blocked", counts.blocked || 0) +
        countChip("Follow-ups due", counts.follow_ups_due || 0) +
        countChip("Rejected", counts.rejected || 0) +
        countChip("Incomplete provenance", counts.incomplete_provenance || 0);
    }
    var rows = (board.top_matches || []).concat(board.sent_outside_top_matches || []).concat(board.incomplete_provenance || []);
    if ($("first-client-list")) {
      $("first-client-list").innerHTML = rows.length
        ? rows.map(card).join("")
        : "<p>No saved opportunities for this owner yet. A failed live search is not shown here as zero matches.</p>";
    }
  }
  function note(id, message) {
    var el = document.getElementById("first-client-note-" + id);
    if (el) el.textContent = message;
  }
  async function load() {
    if (!$("first-client-board")) return;
    if (!token()) {
      if ($("first-client-counts")) $("first-client-counts").textContent = "Sign in to load the board.";
      if ($("first-client-list")) $("first-client-list").innerHTML = "";
      return;
    }
    try {
      render(await api("/api/nova/work/first-client/board"));
    } catch (err) {
      if ($("first-client-counts")) $("first-client-counts").textContent = err.message;
    }
  }
  document.addEventListener("click", async function (event) {
    var button = event.target.closest("[data-first-client-action]");
    if (!button) return;
    var action = button.getAttribute("data-first-client-action");
    var id = button.getAttribute("data-id");
    try {
      if (action === "attempt") {
        await api("/api/nova/work/first-client/applications/" + encodeURIComponent(id) + "/submission-attempt", { method: "POST" });
        note(id, "Blocked handoff recorded. Nothing was sent.");
      } else if (action === "follow-up") {
        var input = document.querySelector("[data-follow-up-for=\"" + id + "\"]");
        if (!input || !input.value) {
          note(id, "Choose a future follow-up time. Nothing was sent.");
          return;
        }
        await api("/api/nova/work/first-client/applications/" + encodeURIComponent(id) + "/follow-up", {
          method: "POST",
          body: JSON.stringify({ follow_up_at: new Date(input.value).toISOString() })
        });
        note(id, "Follow-up saved. Nothing was sent.");
      } else if (action === "ack" || action === "failure") {
        await api("/api/nova/work/first-client/applications/" + encodeURIComponent(id) + "/response", {
          method: "POST",
          body: JSON.stringify({ outcome: action === "ack" ? "ACKNOWLEDGED" : "DELIVERY_FAILURE" })
        });
        note(id, action === "ack" ? "Acknowledgement recorded. Nothing was sent." : "Delivery failure recorded. This is not a delivery.");
      }
      await load();
    } catch (err) {
      note(id, err.message);
    }
  });
  document.addEventListener("nova-work-refreshed", load);
  document.addEventListener("click", function (event) {
    if (event.target && event.target.id === "first-client-refresh") load();
  });
  window.addEventListener("pageshow", load);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") load();
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
