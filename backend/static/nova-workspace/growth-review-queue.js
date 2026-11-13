"use strict";
(function () {
  // Owner-only, read-only workflow preview candidates. No action execution.
  const get = (id) => document.getElementById(id);
  const button = get("growth-agent-preview-queue-load");
  const status = get("growth-agent-preview-queue-status");
  const list = get("growth-agent-preview-queue-list");
  if (!button || !status || !list) return;
  let generation = 0;
  let displayedIdentity = null;
  function owner() {
    const session = window.AmiCorSession;
    const token = session && session.getAccessToken ? session.getAccessToken() : "";
    const org = session && session.getOrganizationId ? session.getOrganizationId() : null;
    const headers = token
      ? (session.getAuthHeaders ? session.getAuthHeaders() : { Authorization: "Bearer " + token })
      : null;
    return { token, org, headers };
  }
  function sameOwner(previous) {
    const current = owner();
    return !!previous.token && current.token === previous.token && current.org === previous.org;
  }
  function clear(message) {
    generation++;
    list.replaceChildren();
    displayedIdentity = null;
    status.textContent = message;
  }
  async function loadQueue() {
    clear("Loading workflow previews…");
    const request = generation;
    const identity = owner();
    if (!identity.headers) {
      status.textContent = "Sign in to view workflow previews.";
      return;
    }
    button.disabled = true;
    try {
      const response = await fetch("/api/nova/growth-agent/workflows/review-queue?limit=50", {
        headers: identity.headers, credentials: "same-origin", cache: "no-store"
      });
      if (request !== generation || !sameOwner(identity)) return;
      if (response.status === 401) throw new Error("Sign in again.");
      if (response.status === 403) throw new Error("Access denied.");
      if (response.status === 404) throw new Error("Growth Agent is unavailable on this service.");
      if (!response.ok) throw new Error("Workflow previews unavailable.");
      const payload = await response.json();
      if (request !== generation || !sameOwner(identity)) return;
      if (!payload || !Array.isArray(payload.items)) throw new Error("Unexpected review-queue response.");
      const nodes = [];
      for (const entry of payload.items.slice(0, 50)) {
        if (!entry || entry.requires_approval !== true ||
            !["preview", "awaiting_approval"].includes(entry.status)) continue;
        const node = document.createElement("li");
        const name = String(entry.workflow_name || entry.workflow_code || "Workflow").slice(0, 100);
        const demo = entry.is_synthetic_demo === true ? "DEMO" : "not marked demo";
        node.textContent = name + " — " + entry.status + " — " + demo +
          (entry.dry_run === true ? " — dry run" : " — mode not confirmed");
        nodes.push(node);
      }
      if (request !== generation || !sameOwner(identity)) return;
      list.replaceChildren(...nodes);
      displayedIdentity = { token: identity.token, org: identity.org };
      status.textContent = nodes.length
        ? nodes.length + " reviewable preview(s) shown. No approvals or sends occurred."
        : "No workflow previews requiring approval in recent results.";
    } catch (err) {
      if (request === generation && sameOwner(identity))
        status.textContent = err.message || "Unable to load workflow previews.";
    } finally {
      if (request === generation) button.disabled = false;
    }
  }
  function checkIdentity() {
    if (displayedIdentity && !sameOwner(displayedIdentity)) clear("Session or organization changed. Reload previews.");
  }
  button.addEventListener("click", loadQueue);
  window.addEventListener("focus", checkIdentity);
  document.addEventListener("visibilitychange", checkIdentity);
  get("sign-out")?.addEventListener("click", () => clear("Sign in to view workflow previews."));
  window.addEventListener("nova:workspace-signed-in", () => clear("Select View workflow previews to review pending work."));
})();
