"use strict";
(function () {
  const button = document.getElementById("central-activity-refresh");
  const output = document.getElementById("central-activity-output");
  if (!button || !output) return;
  const handoffButton = document.getElementById("central-handoff-refresh");
  const handoffOutput = document.getElementById("central-handoff-output");
  if (handoffButton && handoffOutput) {
    handoffButton.addEventListener("click", async () => {
      handoffOutput.textContent = "Checking synthetic handoff...";
      const getHeaders = () => window.AmiCorSession?.getAuthHeaders?.();
      const headers = getHeaders();
      if (!headers?.Authorization) {
        handoffOutput.textContent = "Sign in with your authorized AMICOR owner account first.";
        return;
      }
      handoffButton.disabled = true;
      try {
        const response = await fetch("/api/nova/work/agent-handoff-rehearsal", {
          method: "GET", headers, credentials: "same-origin", cache: "no-store", redirect: "error"
        });
        if (response.status === 401 || response.status === 403) {
          handoffOutput.textContent = "Owner access required. No handoff status returned.";
          return;
        }
        if (!response.ok) throw new Error("Unavailable");
        const data = await response.json();
        const persisted = data?.mode === "read_only_persisted_rehearsal";
        const demo = data?.mode === "read_only_in_memory_demo";
        if (getHeaders()?.Authorization !== headers.Authorization ||
            data?.synthetic !== true || (!persisted && !demo) ||
            !Number.isInteger(data.accepted_count) || data.accepted_count < 0 ||
            data.accepted_count > 4 || data.completed !== (data.accepted_count === 4) ||
            (demo && data.accepted_count !== 4) ||
            data.live_dispatch !== false || data.persistent_storage_connected !== persisted ||
            data.real_approval_verified !== false) throw new Error("Invalid status");
        handoffOutput.textContent = "Synthetic rehearsal: " + data.accepted_count + " of 4 steps completed.\n" +
          "Growth → Work & Revenue → Owner → Operations → Owner.\n" +
          (persisted ? "Read-only persisted rehearsal." : "Read-only demonstration. Persistent storage not connected;") +
          " no real approvals or live dispatch.";
      } catch (_) {
        handoffOutput.textContent = "Rehearsal unavailable. No status shown; no actions taken.";
      } finally { handoffButton.disabled = false; }
    });
  }
  const fields = [
    ["work_opportunities", "Tracked opportunities"],
    ["applications_needing_approval", "Applications awaiting approval"],
    ["follow_ups_due", "Follow-ups due"],
    ["active_engagements", "Active engagements"],
    ["active_tasks", "Active tasks"],
    ["deliverables_pending", "Pending deliverables"],
    ["owner_action_required", "Owner actions required"]
  ];
  button.addEventListener("click", async () => {
    output.textContent = "Checking owner activity...";
    const session = window.AmiCorSession;
    const headers = session && session.getAuthHeaders && session.getAuthHeaders();
    if (!headers || !headers.Authorization) {
      output.textContent = "Sign in with your authorized AMICOR owner account first.";
      return;
    }
    button.disabled = true;
    try {
      const response = await fetch("/api/nova/work/today-summary", {
        method: "GET", headers, credentials: "same-origin", cache: "no-store", redirect: "error"
      });
      if (response.status === 401 || response.status === 403) {
        output.textContent = "Owner access required. No activity returned.";
        return;
      }
      if (!response.ok) throw new Error("Unavailable");
      const data = await response.json();
      if (!data || !fields.every(([key]) => Number.isSafeInteger(data[key]) && data[key] >= 0)) {
        throw new Error("Invalid summary");
      }
      output.textContent = [
        "Work & Revenue — authenticated recorded activity",
        ...fields.map(([key,label]) => label + ": " + data[key]),
        "Records may include simulated entries. Not proof of live customer activity.",
        "Revenue and Stripe payments are not inferred from these counts.",
        "Growth connection: not configured. No actions sent."
      ].join("\n");
    } catch (_) {
      output.textContent = "Activity unavailable. No counts shown; no actions taken.";
    } finally { button.disabled = false; }
  });
})();
