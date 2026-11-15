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
        fetchReadOnly("counts", auth)
      ]);
      var counts = responses[1] && responses[1].counts;
      if (!counts || !["leads", "conversations", "appointments"].every(function (key) {
        return Number.isSafeInteger(counts[key]) && counts[key] >= 0;
      })) {
        throw new Error("Unexpected API format; no counts shown.");
      }
      // Aggregated tenant-scoped counts only: no personal contact records fetched.
      setMessage("Growth Agent API reachable (not proof of live delivery).\n" +
        "Total leads: " + counts.leads + "\n" +
        "Total conversations: " + counts.conversations + "\n" +
        "Total appointments: " + counts.appointments + "\n" +
        "Source: authenticated tenant-scoped summary API. No actions sent.\n" +
        "Owner approvals and Operations handoff: not connected.");
    } catch (error) {
      setMessage("Growth Agent unavailable for this review. " +
        (error && error.message ? error.message : "Network error.") +
        "\nNo actions were taken.");
    } finally { trigger.disabled = false; }
  });
})();
