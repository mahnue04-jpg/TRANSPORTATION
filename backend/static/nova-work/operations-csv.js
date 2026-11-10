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
  if (scoped && scopedStatus) scoped.addEventListener("submit", async function (event) {
    event.preventDefault();
    if (scopedBusy) {
      scopedStatus.textContent = "CSV processing is already in progress. Do not submit again.";
      return;
    }
    const selected = selectedTask;
    const engagement = selected ? String(selected.engagement_id || "") : "";
    const task = selected ? String(selected.task_id || "") : "";
    const file = document.getElementById("operations-scoped-csv-file").files[0];
    const consent = document.getElementById("operations-scope-confirmed").checked;
    const session = window.AmiCorSession;
    const headers = session && typeof session.getAuthHeaders === "function"
      ? session.getAuthHeaders() : {};
    if (!(headers.Authorization || headers.authorization)) {
      scopedStatus.textContent = "Sign in as the AMICOR owner first."; return;
    }
    if (!selected || !engagement || !task || !file || !consent ||
        !eligibleTasks.some(function (item) { return item === selected; })) {
      scopedStatus.textContent = "Select a saved eligible task, choose its CSV, and confirm authorization."; return;
    }
    if (file.size > 1000000) {
      scopedStatus.textContent = "CSV exceeds 1 MB."; return;
    }
    const button = scoped.querySelector('button[type="submit"]');
    scopedBusy = true;
    button.disabled = true;
    if (eligibleSelect) eligibleSelect.disabled = true;
    if (loadEligible) loadEligible.disabled = true;
    scopedStatus.textContent = "Checking saved engagement and processing the CSV...";
    try {
      const url = "/api/nova/work/operations/engagements/" + encodeURIComponent(engagement) +
        "/tasks/" + encodeURIComponent(task) + "/csv-clean";
      const response = await fetch(url, {
        method: "POST", credentials: "same-origin", body: file,
        headers: Object.assign({}, headers, {
          "Content-Type": "text/csv",
          "X-Nova-File-Name": file.name,
          "X-Nova-Owner-Action": "process-csv-for-owner-review",
          "X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization"
        })
      });
      if (!response.ok) {
        let detail = "Processing denied (" + response.status + ").";
        try { const body = await response.json(); detail = body.detail || detail; } catch (_) {}
        scopedStatus.textContent = detail; return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl; link.download = "nova-cleaned-review.csv";
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(function () { URL.revokeObjectURL(objectUrl); }, 10000);
      scopedStatus.textContent = "Saved task " + task +
        ": downloaded " + (response.headers.get("X-Nova-Output-Rows") || "?") +
        " cleaned rows for your review. NOT delivered or marked complete.";
      document.getElementById("operations-scope-confirmed").checked = false;
    } catch (_) {
      scopedStatus.textContent = "Network error. Task was not completed.";
    } finally {
      scopedBusy = false;
      button.disabled = false;
      if (eligibleSelect) eligibleSelect.disabled = false;
      if (loadEligible) loadEligible.disabled = false;
    }
  });
})();