"use strict";
(function () {
  var trigger = document.getElementById("growth-readonly-refresh");
  var result = document.getElementById("growth-readonly-result");
  if (!trigger || !result) return;

  // Intentionally read-only and manually triggered: no public widget, jobs, or outbound traffic.
  function setMessage(message) { result.textContent = message; }
  function session() { return window.AmiCorSession || null; }
  async function fetchReadOnly(path, headers) {
    var response = await fetch("/api/nova/growth-agent/" + path, {
      method: "GET", headers: headers, credentials: "same-origin",
      cache: "no-store"
    });
    if (response.status === 401) throw new Error("Session expired. Sign in again.");
    if (response.status === 403) throw new Error("Access denied for this account.");
    if (response.status === 404) throw new Error("Growth Agent is disabled or unavailable on this environment.");
    if (!response.ok) throw new Error("Growth Agent request failed (" + response.status + ").");
    return response.json();
  }

  trigger.addEventListener("click", async function () {
    var current = session();
    var token = current && current.getAccessToken && current.getAccessToken();
    if (!token) { setMessage("Sign in to Nova Workspace before checking Growth Agent."); return; }
    var auth = current.getAuthHeaders ? current.getAuthHeaders() : { Authorization: "Bearer " + token };
    trigger.disabled = true;
    setMessage("Checking Growth Agent read-only status...");
    try {
      // No customer names, emails, messages or addresses displayed in this introductory panel.
      var responses = await Promise.all([
        fetchReadOnly("health", auth),
        fetchReadOnly("leads", auth),
        fetchReadOnly("conversations", auth),
        fetchReadOnly("appointments", auth)
      ]);
      // Defensive shape checks: a response must not be interpreted as zero if its collection is missing.
      if (!Array.isArray(responses[1].leads) ||
          !Array.isArray(responses[2].conversations) ||
          !Array.isArray(responses[3].appointments)) {
        throw new Error("Unexpected API format; no counts shown.");
      }
      // Only counts are rendered. No hidden customer data is written to HTML.
      setMessage("Growth Agent API reachable (not proof of live delivery).\n" +
        "Leads: " + responses[1].leads.length + "\n" +
        "Conversations: " + responses[2].conversations.length + "\n" +
        "Appointments returned (maximum 50): " + responses[3].appointments.length + "\n" +
        "Source: authenticated API response. No actions sent.\n" +
        "Owner approvals and Operations handoff: not connected.");
    } catch (error) {
      setMessage("Growth Agent unavailable for this review. " +
        (error && error.message ? error.message : "Network error.") +
        "\nNo actions were taken.");
    } finally { trigger.disabled = false; }
  });
})();
