(function () {
  "use strict";
  const prefix = "/api/nova/work/operations/recovery-preview";
  const byId = (name) => document.getElementById(name);
  const message = byId("recovery-message");
  const taskSelect = byId("recovery-task-select");
  const jobSelect = byId("recovery-job-select");
  let tasks = [];
  let pendingRequest = null;
  let busy = false;

  function authHeaders() {
    const session = window.AmiCorSession;
    const headers = session && typeof session.getAuthHeaders === "function"
      ? session.getAuthHeaders() : {};
    if (!(headers && (headers.Authorization || headers.authorization))) {
      throw new Error("Sign in as the AMICOR owner on this staging site first.");
    }
    return headers;
  }

  function activeJob() {
    if (!jobSelect.value) throw new Error("Choose a saved job first.");
    return prefix + "/jobs/" + encodeURIComponent(jobSelect.value);
  }

  async function request(url, options) {
    const opts = options || {};
    const headers = Object.assign({}, authHeaders(), opts.headers || {});
    const response = await fetch(url, Object.assign({
      credentials: "same-origin", headers: headers
    }, opts, {headers: headers}));
    if (!response.ok) {
      let detail = "Request blocked (" + response.status + ").";
      try {
        const payload = await response.json();
        if (typeof payload.detail === "string") detail = payload.detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return response;
  }

  async function action(description, fn) {
    if (busy) return;
    busy = true;
    const controls = Array.from(document.querySelectorAll("button"));
    controls.forEach(button => { button.disabled = true; });
    message.textContent = description;
    try {
      await fn();
    } catch (error) {
      message.textContent = (error && error.message) || "Staging request failed.";
    } finally {
      busy = false;
      controls.forEach(button => { button.disabled = false; });
    }
  }

  byId("recovery-load-tasks").addEventListener("click", function () {
    action("Loading authorized staging tasks...", async function () {
      const response = await request(prefix + "/eligible-csv-tasks");
      const data = await response.json();
      tasks = Array.isArray(data.tasks) ? data.tasks : [];
      taskSelect.replaceChildren(new Option("Choose an assignment", ""));
      tasks.forEach((task, index) => {
        taskSelect.add(new Option(
          (task.engagement_title || task.engagement_id) + " - " +
          (task.task_title || task.task_id), String(index)
        ));
      });
      message.textContent = tasks.length
        ? "Select an assignment and choose a fictional CSV."
        : "No currently eligible assignments found.";
    });
  });

  async function loadHistory(selectId) {
    const response = await request(prefix + "/jobs");
    const data = await response.json();
    const jobs = Array.isArray(data.jobs) ? data.jobs : [];
    jobSelect.replaceChildren(new Option("Choose a saved job", ""));
    jobs.forEach(job => {
      jobSelect.add(new Option(
        (job.status || "UNKNOWN") + " - " +
        (job.engagement_id || "") + " / " + (job.task_id || "") +
        " (" + (job.updated_at || "") + ")", job.job_id
      ));
    });
    if (selectId && jobs.some(job => job.job_id === selectId)) {
      jobSelect.value = selectId;
    }
    message.textContent = jobs.length
      ? "Select a saved job. Status and output remain private."
      : "No accessible saved staging jobs.";
  }

  byId("recovery-load-history").addEventListener("click", function () {
    action("Loading saved staging jobs...", () => loadHistory());
  });

  byId("recovery-upload-form").addEventListener("submit", function (event) {
    event.preventDefault();
    action("Saving fictional CSV into the private staging queue...", async function () {
      const index = taskSelect.value;
      const task = index === "" ? null : tasks[Number(index)];
      const file = byId("recovery-upload").files[0];
      if (!task || !file || !byId("recovery-consent").checked) {
        throw new Error("Select an assignment, a fictional CSV and confirmation.");
      }
      if (!file.name.toLowerCase().endsWith(".csv") ||
          file.size < 1 || file.size > 1000000) {
        throw new Error("CSV must be nonempty, .csv, and at most 1 MB.");
      }
      if (!window.crypto || !window.crypto.randomUUID) {
        throw new Error("Secure request ID generation is unavailable.");
      }
      if (!window.crypto.subtle) {
        throw new Error("Secure file checksum is unavailable in this browser.");
      }
      const fingerprintBytes = await window.crypto.subtle.digest("SHA-256", await file.arrayBuffer());
      const fingerprint = Array.from(new Uint8Array(fingerprintBytes))
        .map(byte => byte.toString(16).padStart(2, "0")).join("");
      const signature = [task.engagement_id, task.task_id, fingerprint].join("|");
      if (!pendingRequest || pendingRequest.signature !== signature) {
        pendingRequest = {signature: signature, key: window.crypto.randomUUID()};
      }
      const key = pendingRequest.key;
      const response = await request(
        prefix + "/engagements/" + encodeURIComponent(task.engagement_id) +
        "/tasks/" + encodeURIComponent(task.task_id) + "/jobs",
        {method: "POST", body: file, headers: {
          "Idempotency-Key": key,
          "Content-Type": "text/csv",
          "X-Nova-File-Name": file.name,
          "X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization"
        }}
      );
      const job = await response.json();
      pendingRequest = null;
      await loadHistory(job.job_id);
      byId("recovery-consent").checked = false;
      message.textContent = "Saved job " + job.job_id +
        " with status " + job.status + ". Not delivered.";
    });
  });

  byId("recovery-check").addEventListener("click", function () {
    action("Reading private job status...", async function () {
      const response = await request(activeJob());
      const job = await response.json();
      message.textContent = "Job " + job.job_id + ": " + job.status +
        ", attempts: " + job.attempts + ". Not delivered.";
    });
  });

  byId("recovery-process").addEventListener("click", function () {
    action("Processing one authorized staging attempt...", async function () {
      const response = await request(activeJob() + "/process", {method: "POST"});
      const result = await response.json();
      const currentId = jobSelect.value;
      await loadHistory(currentId);
      message.textContent = "Job " + result.job_id + ": " + result.status +
        ". Owner review required; not delivered.";
    });
  });

  byId("recovery-download").addEventListener("click", function () {
    action("Retrieving private review copy...", async function () {
      const response = await request(activeJob() + "/download");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "nova-staging-review.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10000);
      message.textContent = "Review copy downloaded. Not sent to a client.";
    });
  });

  async function decide(approve) {
    const response = await request(activeJob() + "/review", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({approve: approve})
    });
    const result = await response.json();
    const currentId = jobSelect.value;
    await loadHistory(currentId);
    message.textContent = "Owner decision: " + result.status +
      ". Not delivered or invoiced.";
  }

  byId("recovery-approve").addEventListener("click", function () {
    action("Recording owner approval...", () => decide(true));
  });
  byId("recovery-reject").addEventListener("click", function () {
    action("Recording owner rejection...", () => decide(false));
  });
})();
