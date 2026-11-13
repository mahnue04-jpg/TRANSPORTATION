"use strict";
(function () {
  // Owner-only, read-only workflow audit viewer. Never initiates a workflow.
  const byId = (id) => document.getElementById(id);
  const loadButton = byId("growth-agent-audit-load");
  const status = byId("growth-agent-audit-status");
  const list = byId("growth-agent-audit-list");
  if (!loadButton || !status || !list) return;
  let requestId = 0;

  function sessionState() {
    const session = window.AmiCorSession;
    const token = session && session.getAccessToken ? session.getAccessToken() : "";
    const org = session && session.getOrganizationId ? session.getOrganizationId() : null;
    const headers = token
      ? (session.getAuthHeaders ? session.getAuthHeaders() : { Authorization: "Bearer " + token })
      : null;
    return { token, org, headers };
  }
  function clear(message) {
    ++requestId;
    list.replaceChildren();
    status.textContent = message;
  }
  function isSameOwner(state) {
    const current = sessionState();
    return !!state.token && state.token === current.token && state.org === current.org;
  }
  async function showWorkflowAudit() {
    const state = sessionState();
    clear("Loading recent workflow history…");
    const request = requestId;
    if (!state.headers) {
      status.textContent = "Sign in to review Growth Agent activity.";
      return;
    }
    loadButton.disabled = true;
    try {
      const response = await fetch("/api/nova/growth-agent/audit?limit=50", {
        headers: state.headers, credentials: "same-origin", cache: "no-store"
      });
      if (request !== requestId || !isSameOwner(state)) return;
      if (response.status === 401) throw new Error("Sign in again.");
      if (response.status === 403) throw new Error("Access denied.");
      if (response.status === 404) throw new Error("Growth Agent is unavailable on this service.");
      if (!response.ok) throw new Error("Audit history unavailable.");
      const payload = await response.json();
      if (request !== requestId || !isSameOwner(state)) return;
      if (!payload || !Array.isArray(payload.events)) throw new Error("Unexpected audit response.");
      const rows = payload.events.filter(row => String(row.action || "").startsWith("workflow.")).slice(0, 20);
      const nodes = rows.map(row => {
        const item = document.createElement("li");
        const action = String(row.action || "workflow event").slice(0, 80);
        const summary = String(row.summary || "").slice(0, 160);
        item.textContent = action + (summary ? " — " + summary : "");
        return item;
      });
      if (request !== requestId || !isSameOwner(state)) return;
      list.replaceChildren(...nodes);
      status.textContent = rows.length
        ? rows.length + " recent workflow audit event(s) shown; activity does not prove external delivery."
        : "No workflow audit events among the latest 50 records.";
    } catch (error) {
      if (request === requestId && isSameOwner(state)) status.textContent = error.message || "Unable to load history.";
    } finally {
      if (request === requestId) loadButton.disabled = false;
    }
  }
  loadButton.addEventListener("click", showWorkflowAudit);
  byId("sign-out")?.addEventListener("click", () => clear("Sign in to review Growth Agent activity."));
  window.addEventListener("nova:workspace-signed-in", () => clear("Select View recent workflow activity to inspect the audit trail."));
})();
