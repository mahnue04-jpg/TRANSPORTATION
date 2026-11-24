"use strict";
(function () {
  const button = document.getElementById("central-activity-refresh");
  const output = document.getElementById("central-activity-output");
  if (!button || !output) return;
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
