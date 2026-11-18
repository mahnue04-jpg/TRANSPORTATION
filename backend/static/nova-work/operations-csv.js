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
  const queuedToggle = document.getElementById("operations-queued-mode");
  const processQueuedButton = document.getElementById("operations-queued-process");
  let currentJobId = "";
  let currentJobMode = "durable";
  let currentJobStatus = "";
  let currentLeaseStatus = "";
  let currentRequest = null;

  function scopedAuthHeaders() {
    const session = window.AmiCorSession;
    const headers = session && typeof session.getAuthHeaders === "function"
      ? session.getAuthHeaders() : {};
    return headers || {};
  }

  function updateJobButtons(status) {
    currentJobStatus = status;
    if (statusButton) statusButton.disabled = !currentJobId;
    const canDownload = currentJobMode === "queued"
      ? status === "APPROVED_FOR_DOWNLOAD"
      : status === "AWAITING_REVIEW" || status === "APPROVED_FOR_DOWNLOAD";
    if (downloadButton) downloadButton.disabled = !currentJobId || !canDownload;
    if (approveButton) approveButton.disabled = !currentJobId || status !== "AWAITING_REVIEW";
    if (rejectButton) rejectButton.disabled = !currentJobId || status !== "AWAITING_REVIEW";
    if (processQueuedButton) processQueuedButton.disabled =
      !currentJobId || currentJobMode !== "queued" || currentLeaseStatus !== "QUEUED";
  }

  function jobPath(suffix) {
    return "/api/nova/work/operations/" + currentJobMode + "/jobs/" +
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
    currentLeaseStatus = job.lease_status || "";
    updateJobButtons(job.status);
    scopedStatus.textContent = "Saved Nova job " + job.job_id + " · " +
      job.status + (job.lease_status ? " (" + job.lease_status + ")" : "") +
      ". Owner review only. Not delivered or paid.";
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
      const queued = Boolean(queuedToggle && queuedToggle.checked);
      const mode = queued ? "queued" : "durable";
      const signature = [selected.engagement_id, selected.task_id,
        file.name, file.size, file.lastModified, mode].join("|");
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
        const url = "/api/nova/work/operations/" + mode + "/engagements/" +
          encodeURIComponent(selected.engagement_id) + "/tasks/"
          encodeURIComponent(selected.task_id) + "/jobs";
        const response = await fetch(url, {
          method: "POST", credentials: "same-origin", body: file,
          headers: Object.assign({}, auth, {
            "Content-Type": "text/csv",
            "X-Nova-File-Name": file.name,
            "X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization",
            "X-Nova-Owner-Action": queued ? "queue-csv-for-owner-review" : "process-csv-for-owner-review",
            "Idempotency-Key": currentRequest.key
          })
        });
        if (!response.ok) throw new Error(await safeError(response));
        const job = await response.json();
        currentJobId = job.job_id || "";
        currentJobMode = mode;
        currentLeaseStatus = queued ? "QUEUED" : "";
        currentRequest = null;
        updateJobButtons(job.status);
        scopedStatus.textContent = "Job " + currentJobId + ": " + job.status +
          (job.replayed ? " (existing request)" : "") +
          (queued ? ". Click Process queued job when authorized." :
            ". Review or download privately.") + " Nothing delivered.";
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
  if (processQueuedButton) processQueuedButton.addEventListener("click", async function () {
    if (!currentJobId || currentJobMode !== "queued" || scopedBusy) return;
    scopedBusy = true;
    processQueuedButton.disabled = true;
    scopedStatus.textContent = "Processing this saved queued job for owner review...";
    try {
      const response = await fetch(jobPath("/process"), {
        method: "POST", credentials: "same-origin",
        headers: Object.assign({}, scopedAuthHeaders(), {
          "X-Nova-Owner-Action": "process-queued-csv-for-owner-review"
        })
      });
      if (!response.ok) throw new Error(await safeError(response));
      const result = await response.json();
      if (result.state === "completed") {
        await refreshJobStatus();
      } else {
        scopedStatus.textContent = "Job " + currentJobId + ": " + result.state +
          ". Processing not confirmed; review status before any action.";
        currentLeaseStatus = result.state === "queued" ? "QUEUED" : "NEEDS_RECONCILIATION";
        updateJobButtons("PROCESSING");
      }
    } catch (err) {
      scopedStatus.textContent = (err && err.message) || "Queued processing unavailable.";
      await refreshJobStatus().catch(function () {});
    } finally {
      scopedBusy = false;
      updateJobButtons(currentJobStatus);
    }
  });
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
      headers: Object.assign({}, scopedAuthHeaders(), {
        "Content-Type": "application/json",
        "X-Nova-Owner-Action": currentJobMode === "queued"
          ? "review-completed-queued-csv" : "review-durable-csv"
      }),
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
