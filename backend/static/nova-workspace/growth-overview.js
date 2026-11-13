"use strict";
(function () {
  // Read-only Growth Agent summary inside the authenticated Nova Workspace.
  const byId = (id) => document.getElementById(id);
  const base = "/api/nova/growth-agent";
  const summary = byId("growth-agent-summary");
  const status = byId("growth-agent-status");
  const refresh = byId("growth-agent-refresh");
  if (!summary || !status || !refresh) return;

  function currentToken() {
    const session = window.AmiCorSession;
    return session && session.getAccessToken ? session.getAccessToken() : "";
  }
  function currentOrganization() {
    const session = window.AmiCorSession;
    return session && session.getOrganizationId ? session.getOrganizationId() : null;
  }
  function authHeaders() {
    const session = window.AmiCorSession;
    if (!session || !session.getAccessToken || !session.getAccessToken()) return null;
    if (session.getAuthHeaders) return session.getAuthHeaders();
    return { Authorization: "Bearer " + session.getAccessToken() };
  }
  async function fetchOwner(path, headers) {
    const response = await fetch(base + path, { headers, credentials: "same-origin", cache: "no-store" });
    if (response.status === 401) throw new Error("Sign in again to view Growth Agent.");
    if (response.status === 403) throw new Error("You do not have access to these Growth Agent records.");
    if (response.status === 404) throw new Error("Growth Agent is unavailable or disabled on this service.");
    if (!response.ok) throw new Error("Growth Agent data could not be loaded (HTTP " + response.status + ").");
    return response.json();
  }
  let requestId = 0;
  async function load() {
    const request = ++requestId;
    const headers = authHeaders();
    const tokenAtStart = currentToken();
    const organizationAtStart = currentOrganization();
    summary.hidden = true;
    if (!headers) { status.textContent = "Sign in to view your Growth Agent activity."; return; }
    refresh.disabled = true;
    status.textContent = "Loading organization-scoped Growth Agent records…";
    try {
      const data = await Promise.all([
        fetchOwner("/flags", headers),
        fetchOwner("/leads", headers),
        fetchOwner("/conversations", headers),
        fetchOwner("/appointments", headers)
      ]);
      if (request !== requestId) return;
      if (!tokenAtStart || currentToken() !== tokenAtStart || currentOrganization() !== organizationAtStart) {
        summary.hidden = true;
        status.textContent = "Session changed; refresh after signing in.";
        return;
      }
      // Do not substitute fake metrics or treat mock reminders as live sends.
      const [flags, leads, conversations, appointments] = data;
      if (!Array.isArray(leads.leads) || !Array.isArray(conversations.conversations) ||
          !Array.isArray(appointments.appointments)) throw new Error("Unexpected Growth Agent API response.");
      function counts(rows) {
        const knownDemo = rows.filter(row => row.is_synthetic_demo === true).length;
        const notMarkedDemo = rows.length - knownDemo;
        return String(rows.length) + " (" + String(notMarkedDemo) + " / " + String(knownDemo) + ")";
      }
      byId("growth-agent-leads").textContent = counts(leads.leads);
      byId("growth-agent-conversations").textContent = counts(conversations.conversations);
      byId("growth-agent-appointments").textContent = counts(appointments.appointments);
      const live = flags.flags || {};
      byId("growth-agent-transport").textContent =
        live.REAL_SMS_SEND || live.REAL_EMAIL_SEND ? "Live transport enabled" : "Mock / no live delivery";
      summary.hidden = false;
      status.textContent = "Recent results loaded. Counts show total (not marked demo / marked demo). They are not lifetime totals or confirmed paying customers.";
    } catch (error) {
      if (request === requestId && currentToken() === tokenAtStart && currentOrganization() === organizationAtStart)
        status.textContent = error.message || "Unable to load Growth Agent.";
    } finally {
      if (request === requestId) refresh.disabled = false;
    }
  }
  refresh.addEventListener("click", load);
  window.addEventListener("focus", () => { if (authHeaders()) load(); });
  // The main Workspace sign-in flow updates the shared session; follow that event.
  window.addEventListener("nova:workspace-signed-in", load);
  byId("sign-out")?.addEventListener("click", () => {
    requestId++;
    summary.hidden = true;
    status.textContent = "Sign in to view your Growth Agent activity.";
  });
  load();
})();
