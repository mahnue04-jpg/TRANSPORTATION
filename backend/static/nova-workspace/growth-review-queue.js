"use strict";
(function () {
  // Owner-only, read-only workflow preview candidates. No action execution.
  const get = (id) => document.getElementById(id);
  const button = get("growth-agent-preview-queue-load");
  const status = get("growth-agent-preview-queue-status");
  const list = get("growth-agent-preview-queue-list");
  if (!button || !status || !list) return;
  let generation = 0;
  let detailGeneration = 0;
  let displayedIdentity = null;
  const detailPanel = get("growth-agent-preview-detail");
  const detailStatus = get("growth-agent-preview-detail-status");
  const detailSteps = get("growth-agent-preview-detail-steps");
  const decisionControls = get("growth-agent-preview-decision-controls");
  const rejectButton = get("growth-agent-preview-reject");
  const requestInfoButton = get("growth-agent-preview-request-information");
  let selected = null;
  let pendingDecision = null;
  let decisionBusy = false;
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
    detailGeneration++;
    selected = null;
    pendingDecision = null;
    if (decisionControls) decisionControls.hidden = true;
    if (rejectButton) { rejectButton.textContent = "Reject workflow"; rejectButton.disabled = false; }
    if (requestInfoButton) { requestInfoButton.textContent = "Request information"; requestInfoButton.disabled = false; }
    if (detailSteps) detailSteps.replaceChildren();
    if (detailPanel) detailPanel.hidden = true;
    displayedIdentity = null;
    status.textContent = message;
  }
  async function viewDetails(runId) {
    const identity = owner();
    const request = ++detailGeneration;
    selected = null;
    pendingDecision = null;
    if (decisionControls) decisionControls.hidden = true;
    if (!identity.headers || !detailPanel || !detailStatus || !detailSteps) return;
    detailSteps.replaceChildren();
    detailPanel.hidden = false;
    detailStatus.textContent = "Loading redacted workflow details…";
    try {
      const response = await fetch(
        "/api/nova/growth-agent/workflows/review-queue/" + encodeURIComponent(runId),
        { headers: identity.headers, credentials: "same-origin", cache: "no-store" }
      );
      if (request !== detailGeneration || !sameOwner(identity)) return;
      if (response.status === 401) throw new Error("Sign in again.");
      if (response.status === 403) throw new Error("Access denied.");
      if (response.status === 404) throw new Error("Workflow no longer available for review.");
      if (!response.ok) throw new Error("Workflow details unavailable.");
      const data = await response.json();
      if (request !== detailGeneration || !sameOwner(identity)) return;
      if (!data || data.run_id !== runId || data.content_redacted !== true ||
          data.requires_approval !== true || !Array.isArray(data.steps) ||
          !["preview", "awaiting_approval"].includes(data.status))
        throw new Error("Unexpected or stale workflow details.");
      const nodes = data.steps.slice(0, 50).map((step, i) => {
        const node = document.createElement("li");
        node.textContent = "Step " + (i + 1) + ": " +
          String(step.channel || "unknown").slice(0, 40) +
          (step.scheduled_for_utc ? " — " + String(step.scheduled_for_utc).slice(0, 35) : "") +
          (step.quiet_hours_adjusted ? " (quiet hours adjusted)" : "");
        return node;
      });
      if (request !== detailGeneration || !sameOwner(identity)) return;
      detailSteps.replaceChildren(...nodes);
      selected = {runId, token: identity.token, org: identity.org};
      if (decisionControls && rejectButton && requestInfoButton) decisionControls.hidden = false;
      detailStatus.textContent = String(data.workflow_name || "Workflow").slice(0, 100) +
        " — " + data.status + " — " + (data.is_synthetic_demo === true ? "DEMO" : "not marked demo") +
        ". Redacted preview only. Nothing approved or sent.";
    } catch (err) {
      if (request === detailGeneration && sameOwner(identity))
        detailStatus.textContent = err.message || "Unable to load workflow details.";
    }
  }

  async function ownerDecision(decision) {
    if (decisionBusy || !["reject", "request_information"].includes(decision)) return;
    const identity = owner();
    if (!selected || !sameOwner(selected) || !sameOwner(identity)) {
      clear("Session changed. Reload workflow previews.");
      return;
    }
    const candidate = selected;
    const actionButton = decision === "reject" ? rejectButton : requestInfoButton;
    if (!actionButton || !rejectButton || !requestInfoButton || !detailStatus) return;
    if (!pendingDecision || pendingDecision.runId !== candidate.runId || pendingDecision.decision !== decision) {
      pendingDecision = {runId: candidate.runId, decision};
      rejectButton.textContent = decision === "reject" ? "Confirm reject (click again)" : "Reject workflow";
      requestInfoButton.textContent = decision === "request_information" ? "Confirm request information (click again)" : "Request information";
      detailStatus.textContent = "Confirm this owner decision by clicking the same button again. Nothing has been changed yet.";
      return;
    }
    // The second owner click performs an authenticated state transition, never execution or delivery.
    decisionBusy = true;
    rejectButton.disabled = true;
    requestInfoButton.disabled = true;
    const generationAtStart = generation;
    const detailAtStart = detailGeneration;
    try {
      const response = await fetch(
        "/api/nova/growth-agent/workflows/review-queue/" + encodeURIComponent(candidate.runId) + "/decision",
        {
          method: "POST", headers: {...identity.headers, "Content-Type": "application/json"},
          credentials: "same-origin", cache: "no-store",
          body: JSON.stringify({decision})
        }
      );
      if (generationAtStart !== generation || detailAtStart !== detailGeneration || !sameOwner(identity)) return;
      if (response.status === 401) throw new Error("Sign in again.");
      if (response.status === 403) throw new Error("Access denied.");
      if (response.status === 409) throw new Error("Workflow decision conflict. Reload before retrying.");
      if (!response.ok) throw new Error("Decision could not be recorded. Reload before retrying.");
      const result = await response.json();
      if (generationAtStart !== generation || detailAtStart !== detailGeneration || !sameOwner(identity)) return;
      if (!result || result.run_id !== candidate.runId || result.decision !== decision ||
          result.execution_performed !== false || result.live_send !== false ||
          result.status !== (decision === "reject" ? "cancelled" : "needs_information"))
        throw new Error("Unexpected decision response. Verify audit history before doing anything else.");
      clear("Owner decision recorded: " + (decision === "reject" ? "Rejected" : "Information requested") +
        ". No workflow executed or message sent. Reload queue to verify.");
    } catch (error) {
      if (generationAtStart === generation && detailAtStart === detailGeneration && sameOwner(identity)) {
        pendingDecision = null;
        detailStatus.textContent = error.message || "Decision not confirmed. Check audit history before retrying.";
      }
    } finally {
      decisionBusy = false;
      if (generationAtStart === generation && detailAtStart === detailGeneration) {
        rejectButton.disabled = false;
        requestInfoButton.disabled = false;
        rejectButton.textContent = "Reject workflow";
        requestInfoButton.textContent = "Request information";
      }
    }
  }
  if (rejectButton) rejectButton.addEventListener("click", () => ownerDecision("reject"));
  if (requestInfoButton) requestInfoButton.addEventListener("click", () => ownerDecision("request_information"));

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
        const detailButton = document.createElement("button");
        detailButton.type = "button";
        detailButton.textContent = "View details";
        detailButton.addEventListener("click", () => viewDetails(String(entry.run_id || "")));
        node.appendChild(detailButton);
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
