(function () {
  "use strict";
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
  const recoveryQueuedButton = document.getElementById("operations-queued-recovery");
  const restoreQueuedButton = document.getElementById("operations-queued-restore");
  const cancelQueuedButton = document.getElementById("operations-queued-cancel");
  let currentJobId = "";
  let currentJobMode = "durable";
  let currentJobStatus = "";
  let currentLeaseStatus = "";
  let currentRecoveryResult = "";
  let currentRequest = null;

  function scopedAuthHeaders() {
    const session = window.AmiCorSession;
    const headers = session && typeof session.getAuthHeaders === "function"
      ? session.getAuthHeaders() : {};
    return headers || {};
  }

  const starterBindButton = document.getElementById("operations-starter-bind");
  const starterProcessButton = document.getElementById("operations-starter-process");
  const starterStatus = document.getElementById("operations-starter-result");
  let starterBoundTask = "";

  function starterSelectedKey() {
    return selectedTask ? selectedTask.engagement_id + "|" + selectedTask.task_id : "";
  }

  function starterAuthorization() {
    const headers = scopedAuthHeaders();
    if (!(headers.Authorization || headers.authorization)) {
      throw new Error("Sign in as the AMICOR owner before processing.");
    }
    if (!selectedTask || !eligibleTasks.includes(selectedTask)) {
      throw new Error("Choose an eligible saved customer task first.");
    }
    if (!document.getElementById("operations-scope-confirmed").checked) {
      throw new Error("Confirm the client's permission to process this specific task.");
    }
    return headers;
  }

  if (starterBindButton && starterStatus) {
    starterBindButton.addEventListener("click", async function () {
      if (scopedBusy) return;
      starterBoundTask = "";
      let auth;
      try { auth = starterAuthorization(); }
      catch (error) { starterStatus.textContent = error.message; return; }
      const leadInput = document.getElementById("operations-starter-lead");
      const leadId = (leadInput && leadInput.value || "").trim();
      if (!/^[a-zA-Z0-9_-]{1,36}$/.test(leadId)) {
        starterStatus.textContent = "Enter the saved paid Operations lead ID (not a Stripe card or bank number).";
        return;
      }
      const taskKey = starterSelectedKey();
      scopedBusy = true;
      starterBindButton.disabled = true;
      starterStatus.textContent = "Checking the saved verified $49 checkout and matching customer task...";
      try {
        const url = "/api/nova/work/operations/engagements/" +
          encodeURIComponent(selectedTask.engagement_id) + "/tasks/" +
          encodeURIComponent(selectedTask.task_id) + "/starter-payment-bindings/" +
          encodeURIComponent(leadId);
        const response = await fetch(url, {
          method: "POST", credentials: "same-origin",
          headers: Object.assign({}, auth, {
            "X-Nova-Owner-Action": "bind-paid-starter-to-task"
          })
        });
        if (!response.ok) throw new Error(await safeError(response));
        starterBoundTask = taskKey;
        starterStatus.textContent = "Saved $49 payment bound to this task for owner review. No customer file has been processed or delivered.";
      } catch (error) {
        starterStatus.textContent = error.message ||
          "Unable to verify the payment-to-task binding. Do not process customer data.";
      } finally {
        scopedBusy = false;
        starterBindButton.disabled = false;
      }
    });
  }

  if (starterProcessButton && starterStatus) {
    starterProcessButton.addEventListener("click", async function () {
      if (scopedBusy) return;
      let auth;
      try { auth = starterAuthorization(); }
      catch (error) { starterStatus.textContent = error.message; return; }
      if (!starterBoundTask || starterBoundTask !== starterSelectedKey()) {
        starterStatus.textContent = "Bind the verified $49 payment to this exact task first.";
        return;
      }
      const fileInput = document.getElementById("operations-scoped-csv-file");
      const file = fileInput && fileInput.files[0];
      if (!file || !file.name.toLowerCase().endsWith(".csv") ||
          file.size < 1 || file.size > 1000000) {
        starterStatus.textContent = "Choose an authorized UTF-8 CSV file up to 1 MB.";
        return;
      }
      scopedBusy = true;
      starterProcessButton.disabled = true;
      starterStatus.textContent = "Processing the paid, authorized task for owner review only...";
      try {
        const url = "/api/nova/work/operations/engagements/" +
          encodeURIComponent(selectedTask.engagement_id) + "/tasks/" +
          encodeURIComponent(selectedTask.task_id) + "/csv-clean";
        const response = await fetch(url, {
          method: "POST", credentials: "same-origin", body: file,
          headers: Object.assign({}, auth, {
            "Content-Type": "text/csv",
            "X-Nova-File-Name": file.name,
            "X-Nova-Owner-Action": "process-csv-for-owner-review",
            "X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization"
          })
        });
        if (!response.ok) throw new Error(await safeError(response));
        const blob = await response.blob();
        const temporaryUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = temporaryUrl;
        link.download = "nova-starter-owner-review.csv";
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(function () { URL.revokeObjectURL(temporaryUrl); }, 10000);
        starterStatus.textContent = "Review-only CSV downloaded locally. Customer delivery and task completion are NOT automatic.";
      } catch (error) {
        starterStatus.textContent = error.message ||
          "Owner-reviewed processing unavailable. Do not send an unapproved file.";
      } finally {
        scopedBusy = false;
        starterProcessButton.disabled = false;
      }
    });
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
    if (recoveryQueuedButton) recoveryQueuedButton.disabled =
      !currentJobId || currentJobMode !== "queued";
    if (restoreQueuedButton) restoreQueuedButton.disabled =
      !currentJobId || currentJobMode !== "queued" ||
      currentRecoveryResult !== "input_binding_incomplete";
    if (cancelQueuedButton) cancelQueuedButton.disabled =
      !currentJobId || currentJobMode !== "queued" ||
      !["QUEUED", "RUNNING"].includes(currentLeaseStatus);
    updateDeliveryButtons();
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
    if (currentLeaseStatus !== "QUEUED") currentRecoveryResult = "";
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
          encodeURIComponent(selected.engagement_id) + "/tasks/" +
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
        currentRecoveryResult = "";
        // Keep the same key for identical queued resubmissions; an owner must
        // change task, file or mode to intentionally start new work.
        if (!queued) currentRequest = null;
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
  if (recoveryQueuedButton) recoveryQueuedButton.addEventListener("click", async function () {
    if (!currentJobId || currentJobMode !== "queued" || scopedBusy) return;
    recoveryQueuedButton.disabled = true;
    try {
      const response = await fetch(jobPath("/recovery"), {
        credentials: "same-origin", headers: scopedAuthHeaders()
      });
      if (!response.ok) throw new Error(await safeError(response));
      const result = await response.json();
      currentRecoveryResult = result.recovery_result || "";
      scopedStatus.textContent = "Recovery inspection: " + result.recovery_result +
        (result.owner_action_required ? ". Owner review required." : ".") +
        " No automatic retry or customer delivery.";
      await refreshJobStatus();
    } catch (err) {
      scopedStatus.textContent = (err && err.message) || "Recovery inspection unavailable.";
    } finally {
      updateJobButtons(currentJobStatus);
    }
  });
  if (restoreQueuedButton) restoreQueuedButton.addEventListener("click", async function () {
    if (!currentJobId || currentJobMode !== "queued" || scopedBusy ||
        currentRecoveryResult !== "input_binding_incomplete") return;
    const fileInput = document.getElementById("operations-scoped-csv-file");
    const file = fileInput && fileInput.files[0];
    if (!file || !file.name.toLowerCase().endsWith(".csv") || file.size === 0 ||
        file.size > 1000000) {
      scopedStatus.textContent = "Choose the original CSV file (1 MB maximum) for this reserved job.";
      return;
    }
    if (!window.confirm("Restore the original CSV to this existing job? Previous interrupted uploads may leave private objects requiring separate cleanup.")) return;
    scopedBusy = true;
    restoreQueuedButton.disabled = true;
    try {
      const response = await fetch(jobPath("/restore-input"), {
        method: "POST", credentials: "same-origin", body: file,
        headers: Object.assign({}, scopedAuthHeaders(), {
          "Content-Type": "text/csv",
          "X-Nova-File-Name": file.name,
          "X-Nova-Owner-Action": "restore-unbound-csv-input"
        })
      });
      if (!response.ok) throw new Error(await safeError(response));
      const result = await response.json();
      currentRecoveryResult = "";
      scopedStatus.textContent = "Original CSV input restored to job " + result.job_id +
        ". No work delivered. Separate orphan cleanup may still be needed.";
      await refreshJobStatus();
    } catch (err) {
      scopedStatus.textContent = (err && err.message) || "CSV restore unavailable.";
      await refreshJobStatus().catch(function () {});
    } finally {
      scopedBusy = false;
      updateJobButtons(currentJobStatus);
    }
  });
  if (cancelQueuedButton) cancelQueuedButton.addEventListener("click", async function () {
    if (!currentJobId || currentJobMode !== "queued" || scopedBusy) return;
    if (!window.confirm("Cancel this queued job? This cannot undo any private output already written.")) return;
    scopedBusy = true;
    cancelQueuedButton.disabled = true;
    try {
      const response = await fetch(jobPath("/cancel"), {
        method: "POST", credentials: "same-origin",
        headers: Object.assign({}, scopedAuthHeaders(), {
          "X-Nova-Owner-Action": "cancel-queued-csv-job"
        })
      });
      if (!response.ok) throw new Error(await safeError(response));
      const result = await response.json();
      currentLeaseStatus = result.lease_status || "CANCELLED";
      scopedStatus.textContent = "Queued job canceled. No automatic retry or delivery.";
      updateJobButtons(currentJobStatus);
    } catch (err) {
      scopedStatus.textContent = (err && err.message) || "Cancellation unavailable.";
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
  const deliveryGrantButton = document.getElementById("operations-delivery-grant");
  const deliveryRevokeButton = document.getElementById("operations-delivery-revoke");
  const deliveryResult = document.getElementById("operations-delivery-result");

  function updateDeliveryButtons() {
    const ready = !!currentJobId && currentJobMode === "durable" &&
      currentJobStatus === "APPROVED_FOR_DOWNLOAD" && !scopedBusy;
    if (deliveryGrantButton) deliveryGrantButton.disabled = !ready;
    if (deliveryRevokeButton) deliveryRevokeButton.disabled = !ready;
  }

  if (deliveryGrantButton && deliveryResult) {
    deliveryGrantButton.addEventListener("click", async function () {
      if (scopedBusy || currentJobMode !== "durable" ||
          currentJobStatus !== "APPROVED_FOR_DOWNLOAD" || !currentJobId) {
        deliveryResult.textContent = "Approve a durable task before granting customer access.";
        return;
      }
      const headers = scopedAuthHeaders();
      if (!(headers.Authorization || headers.authorization)) {
        deliveryResult.textContent = "Sign in as the authorized AMICOR owner.";
        return;
      }
      if (!window.confirm("Grant this verified customer access to the approved $49 CSV for 24 hours?")) return;
      scopedBusy = true;
      updateDeliveryButtons();
      deliveryResult.textContent = "Verifying paid task, customer identity, and approved private artifact...";
      try {
        const url = "/api/nova/work/operations/owner/jobs/" +
          encodeURIComponent(currentJobId) + "/delivery-grants/by-paid-order";
        const response = await fetch(url, {
          method: "POST", credentials: "same-origin",
          headers: Object.assign({}, headers, {
            "X-Nova-Owner-Action": "issue-approved-csv-delivery"
          })
        });
        if (!response.ok) throw new Error(await safeError(response));
        const data = await response.json();
        deliveryResult.textContent = data.grant_status === "issued"
          ? "Customer download granted for 24 hours. No notification sent; delivery receipt not confirmed."
          : "Grant result needs owner review.";
      } catch (error) {
        deliveryResult.textContent = error.message || "Customer delivery is unavailable.";
      } finally {
        scopedBusy = false;
        updateDeliveryButtons();
      }
    });
  }

  if (deliveryRevokeButton && deliveryResult) {
    deliveryRevokeButton.addEventListener("click", async function () {
      if (scopedBusy || !currentJobId || currentJobMode !== "durable") return;
      if (!window.confirm("Revoke this customer's current download access?")) return;
      const headers = scopedAuthHeaders();
      if (!(headers.Authorization || headers.authorization)) {
        deliveryResult.textContent = "Sign in as the authorized AMICOR owner.";
        return;
      }
      scopedBusy = true;
      updateDeliveryButtons();
      try {
        const url = "/api/nova/work/operations/owner/jobs/" +
          encodeURIComponent(currentJobId) + "/delivery-grants/revoke";
        const response = await fetch(url, {
          method: "POST", credentials: "same-origin",
          headers: Object.assign({}, headers, {
            "X-Nova-Owner-Action": "revoke-csv-delivery"
          })
        });
        if (!response.ok) throw new Error(await safeError(response));
        deliveryResult.textContent = "Customer download permission revoked.";
      } catch (error) {
        deliveryResult.textContent = error.message || "Revocation is unavailable.";
      } finally {
        scopedBusy = false;
        updateDeliveryButtons();
      }
    });
  }
  updateDeliveryButtons();

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
