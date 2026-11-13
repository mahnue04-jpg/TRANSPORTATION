(function () {
  "use strict";
  const form = document.getElementById("operations-csv-form");
  const message = document.getElementById("operations-csv-result");
  if (!form || !message) return;
  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const file = document.getElementById("operations-csv-file").files[0];
    const button = form.querySelector('button[type="submit"]');
    if (!file) { message.textContent = "Choose a CSV file."; return; }
    if (file.size > 1000000) { message.textContent = "File must be no larger than 1 MB."; return; }
    const session = window.AmiCorSession;
    const headers = session && typeof session.getAuthHeaders === "function"
      ? session.getAuthHeaders() : {};
    if (!headers || !(headers.Authorization || headers.authorization)) {
      message.textContent = "Sign in as the AMICOR Work & Revenue owner first.";
      return;
    }
    button.disabled = true;
    message.textContent = "Processing CSV for owner review...";
    try {
      const response = await fetch("/api/nova/work/operations/csv-clean", {
        method: "POST",
        credentials: "same-origin",
        headers: Object.assign({}, headers, {
          "X-Nova-Owner-Action": "process-csv-for-owner-review",
          "X-Nova-File-Name": file.name,
          "Content-Type": "text/csv"
        }),
        body: file
      });
      if (!response.ok) {
        let detail = "Request failed (" + response.status + ").";
        try { const payload = await response.json(); detail = payload.detail || detail; } catch (_) {}
        message.textContent = detail;
        return;
      }
      const cleaned = await response.blob();
      const downloadUrl = URL.createObjectURL(cleaned);
      const anchor = document.createElement("a");
      anchor.href = downloadUrl;
      anchor.download = "nova-cleaned-review.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(function () { URL.revokeObjectURL(downloadUrl); }, 10000);
      message.textContent = "Review required: " +
        (response.headers.get("X-Nova-Input-Rows") || "?") + " input rows, " +
        (response.headers.get("X-Nova-Output-Rows") || "?") +
        " cleaned rows. Downloaded for your inspection. No file was saved by the application.";
    } catch (_) {
      message.textContent = "Could not connect. Please check your sign-in and network.";
    } finally {
      button.disabled = false;
    }
  });
  const loadEligible = document.getElementById("operations-load-eligible");
  const eligibleSelect = document.getElementById("operations-eligible-select");
  let eligibleTasks = [];
  let selectedTask = null;
  let scopedBusy = false;
  if (loadEligible && eligibleSelect) {
    loadEligible.addEventListener("click", async function () {
      const session = window.AmiCorSession;
      const headers = session && typeof session.getAuthHeaders === "function"
        ? session.getAuthHeaders() : {};
      const status = document.getElementById("operations-scoped-csv-result");
      if (!(headers.Authorization || headers.authorization)) {
        selectedTask = null;
        eligibleTasks = [];
        eligibleSelect.replaceChildren(new Option("Sign in to load tasks", ""));
        status.textContent = "Sign in as the AMICOR owner first."; return;
      }
      if (scopedBusy) {
        status.textContent = "Finish the current CSV review request before reloading tasks.";
        return;
      }
      loadEligible.disabled = true;
      selectedTask = null;
      eligibleTasks = [];
      eligibleSelect.replaceChildren(new Option("Loading eligible tasks...", ""));
      document.getElementById("operations-scope-confirmed").checked = false;
      status.textContent = "Loading eligible Nova tasks...";
      try {
        const response = await fetch("/api/nova/work/operations/eligible-csv-tasks", {
          credentials: "same-origin", headers: headers
        });
        if (!response.ok) {
          let detail = "Task lookup unavailable (" + response.status + ").";
          try { const error = await response.json(); detail = error.detail || detail; } catch (_) {}
          eligibleSelect.replaceChildren(new Option("No tasks available", ""));
          status.textContent = detail; return;
        }
        const data = await response.json();
        eligibleTasks = Array.isArray(data.tasks) ? data.tasks : [];
        eligibleSelect.replaceChildren(new Option("Choose a saved task", ""));
        eligibleTasks.forEach(function (task, index) {
          const label = (task.engagement_title || task.engagement_id) +
            " — " + (task.task_title || task.task_id);
          eligibleSelect.appendChild(new Option(label, String(index)));
        });
        status.textContent = eligibleTasks.length
          ? "Select a saved task, then confirm authority and choose its CSV."
          : "No eligible Nova tasks were found. An ACTIVE engagement and an unblocked Nova review task are required.";
      } catch (_) {
        eligibleSelect.replaceChildren(new Option("Could not load tasks", ""));
        status.textContent = "Could not load saved tasks. Check your connection.";
      } finally {
        loadEligible.disabled = false;
      }
    });
    eligibleSelect.addEventListener("change", function () {
      if (scopedBusy) return;
      selectedTask = null;
      document.getElementById("operations-scope-confirmed").checked = false;
      const index = Number(eligibleSelect.value);
      if (eligibleSelect.value === "" || !Number.isInteger(index) || !eligibleTasks[index]) return;
      selectedTask = eligibleTasks[index];
    });
  }
  const scoped = document.getElementById("operations-scoped-csv-form");
  const scopedStatus = document.getElementById("operations-scoped-csv-result");
  const statusButton = document.getElementById("operations-durable-status");
  const downloadButton = document.getElementById("operations-durable-download");
  const approveButton = document.getElementById("operations-durable-approve");
  const rejectButton = document.getElementById("operations-durable-reject");
  let currentJobId = "";
  let currentRequest = null;

  function scopedAuthHeaders() {
    const session = window.AmiCorSession;
    const headers = session && typeof session.getAuthHeaders === "function"
      ? session.getAuthHeaders() : {};
    return headers || {};
  }

  function updateJobButtons(status) {
    if (statusButton) statusButton.disabled = !currentJobId;
    const canDownload = status === "AWAITING_REVIEW" || status === "APPROVED_FOR_DOWNLOAD";
    if (downloadButton) downloadButton.disabled = !currentJobId || !canDownload;
    if (approveButton) approveButton.disabled = !currentJobId || status !== "AWAITING_REVIEW";
    if (rejectButton) rejectButton.disabled = !currentJobId || status !== "AWAITING_REVIEW";
  }

  function jobPath(suffix) {
    return "/api/nova/work/operations/durable/jobs/" +
      encodeURIComponent(currentJobId) + (suffix || "");
  }

  async function safeError(response) {
    let message = "Nova request failed (" + response.status + ").";
    try {
      const parsed = await response.json();
      if (typeof parsed.detail === "string") message = parsed.detail;
    } catch (_) {}
    return message;
  }

  async function refreshJobStatus() {
    if (!currentJobId) return;
    const response = await fetch(jobPath(""), {
      credentials: "same-origin", headers: scopedAuthHeaders()
    });
    if (!response.ok) throw new Error(await safeError(response));
    const job = await response.json();
    updateJobButtons(job.status);
    scopedStatus.textContent = "Saved Nova job " + job.job_id + " · " +
      job.status + ". Owner review only. Not delivered or paid.";
  }

  const historyRefresh = document.getElementById("operations-durable-history-refresh");
  const historySelect = document.getElementById("operations-durable-history-select");
  const historyOpen = document.getElementById("operations-durable-history-open");
  const historyStatus = document.getElementById("operations-durable-history-result");
  if (historyRefresh && historySelect && historyOpen && historyStatus) {
    historySelect.addEventListener("change", function () {
      historyOpen.disabled = !historySelect.value;
    });
    historyRefresh.addEventListener("click", async function () {
      historyRefresh.disabled = true;
      historyOpen.disabled = true;
      historySelect.replaceChildren(new Option("Loading saved jobs...", ""));
      historyStatus.textContent = "Loading saved owner jobs...";
      try {
        const auth = scopedAuthHeaders();
        if (!(auth.Authorization || auth.authorization)) {
          throw new Error("Sign in as the AMICOR owner first.");
        }
        const response = await fetch("/api/nova/work/operations/durable/jobs", {
          credentials: "same-origin", headers: auth
        });
        if (!response.ok) throw new Error(await safeError(response));
        const data = await response.json();
        const jobs = Array.isArray(data.jobs) ? data.jobs : [];
        historySelect.replaceChildren(new Option("Choose a saved job", ""));
        jobs.forEach(function (job) {
          const label = (job.status || "UNKNOWN") + " · " +
            (job.engagement_id || "") + " / " + (job.task_id || "") +
            " · " + (job.created_at || "");
          historySelect.appendChild(new Option(label, job.job_id));
        });
        historyStatus.textContent = jobs.length
          ? "Select an authorized job to reopen its review controls."
          : "No accessible saved jobs. Disabled durable processing does not erase earlier records.";
      } catch (err) {
        historySelect.replaceChildren(new Option("Saved jobs unavailable", ""));
        historyStatus.textContent = err.message || "Unable to load saved jobs.";
      } finally {
        historyRefresh.disabled = false;
      }
    });
    historyOpen.addEventListener("click", async function () {
      const selectedId = historySelect.value;
      if (!selectedId) return;
      const previousId = currentJobId;
      currentJobId = selectedId;
      historyOpen.disabled = true;
      try {
        await refreshJobStatus();
        historyStatus.textContent = "Job reopened for owner review. No customer delivery.";
      } catch (err) {
        currentJobId = previousId;
        updateJobButtons("");
        historyStatus.textContent = err.message || "Unable to reopen job.";
      } finally {
        historyOpen.disabled = !historySelect.value;
      }
    });
  }

  const recoveryPreviewButton = document.getElementById("operations-recovery-preview");
  const recoveryApplyButton = document.getElementById("operations-recovery-apply");
  const recoveryConfirm = document.getElementById("operations-recovery-confirm");
  const recoveryStatus = document.getElementById("operations-recovery-result");
  let recoveryPreview = null;
  let recoveryBusy = false;

  function clearRecoveryPreview() {
    recoveryPreview = null;
    if (recoveryApplyButton) recoveryApplyButton.disabled = true;
    if (recoveryConfirm) recoveryConfirm.checked = false;
  }

  if (recoveryPreviewButton && recoveryApplyButton && recoveryConfirm && recoveryStatus) {
    recoveryConfirm.addEventListener("change", function () {
      recoveryApplyButton.disabled = recoveryBusy || !recoveryPreview ||
        !recoveryPreview.length || !recoveryConfirm.checked;
    });
    recoveryPreviewButton.addEventListener("click", async function () {
      if (recoveryBusy) return;
      clearRecoveryPreview();
      const auth = scopedAuthHeaders();
      if (!(auth.Authorization || auth.authorization)) {
        recoveryStatus.textContent = "Sign in as the AMICOR owner first.";
        return;
      }
      recoveryBusy = true;
      recoveryPreviewButton.disabled = true;
      recoveryStatus.textContent = "Checking authorized stalled jobs...";
      try {
        const response = await fetch("/api/nova/work/operations/durable/jobs/recover-stale-batch", {
          method: "POST", credentials: "same-origin",
          headers: Object.assign({}, auth, {"Content-Type": "application/json"}),
          body: JSON.stringify({apply: false, limit: 25})
        });
        if (!response.ok) throw new Error(await safeError(response));
        const data = await response.json();
        const ids = Array.isArray(data.candidate_job_ids) ? data.candidate_job_ids : [];
        recoveryPreview = ids;
        recoveryStatus.textContent = ids.length
          ? ids.length + " stalled job(s) eligible for failure recovery. Review carefully, check the confirmation box, then apply."
          : "No authorized stalled jobs found. No changes made.";
      } catch (err) {
        clearRecoveryPreview();
        recoveryStatus.textContent = err.message || "Recovery preview unavailable.";
      } finally {
        recoveryBusy = false;
        recoveryPreviewButton.disabled = false;
      }
    });
    recoveryApplyButton.addEventListener("click", async function () {
      if (recoveryBusy || !recoveryConfirm.checked || !recoveryPreview || !recoveryPreview.length) return;
      const selected = recoveryPreview.slice();
      clearRecoveryPreview();
      recoveryBusy = true;
      recoveryPreviewButton.disabled = true;
      recoveryStatus.textContent = "Applying recovery only to the previewed stalled jobs...";
      try {
        const auth = scopedAuthHeaders();
        if (!(auth.Authorization || auth.authorization)) {
          throw new Error("Sign in as the AMICOR owner first.");
        }
        const response = await fetch("/api/nova/work/operations/durable/jobs/recover-stale-batch", {
          method: "POST", credentials: "same-origin",
          headers: Object.assign({}, auth, {
            "Content-Type": "application/json",
            "X-Nova-Owner-Action": "recover-previewed-stale-jobs"
          }),
          body: JSON.stringify({apply: true, limit: 25, expected_job_ids: selected})
        });
        if (!response.ok) throw new Error(await safeError(response));
        const data = await response.json();
        recoveryStatus.textContent = String(data.recovered_count || 0) +
          " stalled job(s) marked FAILED. No customer files restarted or delivered; inspect failures and reupload with new authorization.";
      } catch (err) {
        recoveryStatus.textContent = (err.message || "Recovery failed.") +
          " Refresh the preview before any retry.";
      } finally {
        recoveryBusy = false;
        recoveryPreviewButton.disabled = false;
      }
    });
  }

  if (scoped && scopedStatus) {
    scoped.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (scopedBusy) {
        scopedStatus.textContent = "A CSV job request is already running.";
        return;
      }
      const selected = selectedTask;
      const file = document.getElementById("operations-scoped-csv-file").files[0];
      const consent = document.getElementById("operations-scope-confirmed").checked;
      const auth = scopedAuthHeaders();
      if (!(auth.Authorization || auth.authorization)) {
        scopedStatus.textContent = "Sign in as the AMICOR owner first."; return;
      }
      if (!selected || !eligibleTasks.includes(selected) || !file || !consent) {
        scopedStatus.textContent = "Choose a saved eligible task, a CSV, and confirm permission."; return;
      }
      if (!file.name.toLowerCase().endsWith(".csv") || file.size < 1 || file.size > 1000000) {
        scopedStatus.textContent = "CSV file must be nonempty and no larger than 1 MB."; return;
      }
      const signature = [selected.engagement_id, selected.task_id,
        file.name, file.size, file.lastModified].join("|");
      if (!currentRequest || currentRequest.signature !== signature) {
        if (!window.crypto || typeof window.crypto.randomUUID !== "function") {
          scopedStatus.textContent = "Secure request ID unavailable in this browser."; return;
        }
        currentRequest = { signature: signature, key: window.crypto.randomUUID() };
      }
      const submitButton = scoped.querySelector('button[type="submit"]');
      scopedBusy = true;
      submitButton.disabled = true;
      if (eligibleSelect) eligibleSelect.disabled = true;
      if (loadEligible) loadEligible.disabled = true;
      scopedStatus.textContent = "Submitting authorized CSV to private review processing...";
      try {
        const url = "/api/nova/work/operations/durable/engagements/" +
          encodeURIComponent(selected.engagement_id) + "/tasks/" +
          encodeURIComponent(selected.task_id) + "/jobs";
        const response = await fetch(url, {
          method: "POST", credentials: "same-origin", body: file,
          headers: Object.assign({}, auth, {
            "Content-Type": "text/csv",
            "X-Nova-File-Name": file.name,
            "X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization",
            "Idempotency-Key": currentRequest.key
          })
        });
        if (!response.ok) throw new Error(await safeError(response));
        const job = await response.json();
        currentJobId = job.job_id || "";
        currentRequest = null;
        updateJobButtons(job.status);
        scopedStatus.textContent = "Job " + currentJobId + ": " + job.status +
          (job.replayed ? " (existing request)" : "") +
          ". Review or download privately; nothing delivered.";
        document.getElementById("operations-scope-confirmed").checked = false;
      } catch (err) {
        scopedStatus.textContent = (err && err.message) ||
          "CSV request failed. Retry uses the same request key.";
      } finally {
        scopedBusy = false;
        submitButton.disabled = false;
        if (eligibleSelect) eligibleSelect.disabled = false;
        if (loadEligible) loadEligible.disabled = false;
      }
    });
  }
  if (statusButton) statusButton.addEventListener("click", async function () {
    try { await refreshJobStatus(); }
    catch (err) { scopedStatus.textContent = err.message; }
  });
  if (downloadButton) downloadButton.addEventListener("click", async function () {
    if (!currentJobId) return;
    downloadButton.disabled = true;
    try {
      const response = await fetch(jobPath("/download"), {
        credentials: "same-origin", headers: scopedAuthHeaders()
      });
      if (!response.ok) throw new Error(await safeError(response));
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = "nova-cleaned-review.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(function () { URL.revokeObjectURL(objectUrl); }, 10000);
      scopedStatus.textContent = "Private review copy downloaded. Not delivered to a client.";
    } catch (err) { scopedStatus.textContent = err.message; }
    finally { downloadButton.disabled = false; }
  });
  async function decideJob(approve) {
    if (!currentJobId) return;
    const response = await fetch(jobPath("/review"), {
      method: "POST", credentials: "same-origin",
      headers: Object.assign({}, scopedAuthHeaders(), {"Content-Type": "application/json"}),
      body: JSON.stringify({approve: approve})
    });
    if (!response.ok) throw new Error(await safeError(response));
    const job = await response.json();
    updateJobButtons(job.status);
    scopedStatus.textContent = "Owner decision: " + job.status +
      ". No customer delivery or payment occurred.";
  }
  if (approveButton) approveButton.addEventListener("click", async function () {
    approveButton.disabled = true;
    try { await decideJob(true); }
    catch (err) { scopedStatus.textContent = err.message; await refreshJobStatus().catch(function () {}); }
  });
  if (rejectButton) rejectButton.addEventListener("click", async function () {
    rejectButton.disabled = true;
    try { await decideJob(false); }
    catch (err) { scopedStatus.textContent = err.message; await refreshJobStatus().catch(function () {}); }
  });
})();
