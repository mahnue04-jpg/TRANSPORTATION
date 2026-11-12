(function () {
  "use strict";
  const root = document.getElementById("nova-bookkeeping-console");
  if (!root) return;

  const byId = id => document.getElementById(id);
  const message = byId("bookkeeping-message");
  const nextAction = byId("bookkeeping-next-action");
  const select = byId("bookkeeping-job-select");
  const load = byId("bookkeeping-load-queue");
  const status = byId("bookkeeping-status");
  const download = byId("bookkeeping-download");
  const approve = byId("bookkeeping-approve");
  const reject = byId("bookkeeping-reject");
  const recover = byId("bookkeeping-recover");
  const submit = byId("bookkeeping-submit-form");
  const submitButton = byId("bookkeeping-submit-button");
  const loadTasks = byId("bookkeeping-load-tasks");
  const taskSelect = byId("bookkeeping-eligible-tasks");
  let availableTasks = [];
  let selectedTask = null;
  const kind = byId("bookkeeping-kind");
  const asOf = byId("bookkeeping-as-of");
  const prefix = "/api/nova/work/operations/durable/bookkeeping";
  const actionNames = {
    review_draft_and_decide: "Review the private workpaper and decide",
    download_owner_review_copy: "Download your approved review copy",
    inspect_failure_then_new_request: "Inspect failure; use a new request ID to retry",
    check_status_or_recover_if_stale: "Check processing status; recover only if stale",
    no_delivery: "Rejected; nothing delivered",
    contact_operator: "Contact the operator for manual review"
  };
  let queue = [];
  let selected = null;
  let busy = false;
  let lastSubmission = null;
  const controls = [load, status, download, approve, reject, recover, submitButton];

  function auth() {
    const session = window.AmiCorSession;
    const headers = session && typeof session.getAuthHeaders === "function"
      ? session.getAuthHeaders() : {};
    return headers || {};
  }
  function signedIn(headers) {
    return !!(headers.Authorization || headers.authorization);
  }
  function reset() {
    queue = [];
    selected = null;
    availableTasks = [];
    selectedTask = null;
    taskSelect.replaceChildren(new Option("Load authorized tasks first", ""));
    byId("bookkeeping-engagement").value = "";
    byId("bookkeeping-task").value = "";
    select.replaceChildren(new Option("Load your authorized review queue", ""));
    nextAction.textContent = "No saved accounting job selected.";
    update();
  }
  function update() {
    const hasJob = !!selected;
    const ready = !busy && hasJob;
    load.disabled = busy;
    loadTasks.disabled = busy;
    taskSelect.disabled = busy;
    status.disabled = !ready;
    download.disabled = !ready || !["AWAITING_REVIEW", "APPROVED_FOR_DOWNLOAD"].includes(selected.status);
    approve.disabled = !ready || selected.status !== "AWAITING_REVIEW";
    reject.disabled = !ready || selected.status !== "AWAITING_REVIEW";
    recover.disabled = !ready || selected.status !== "PROCESSING";
    submitButton.disabled = busy;
    if (selected) {
      const summary = actionNames[selected.next_action] || "Check the current job status";
      nextAction.textContent = "Status: " + selected.status + ". Next action: " + summary + ". Never delivered.";
    }
  }
  function setBusy(value) { busy = !!value; update(); }
  function errorText(payload, code) {
    return typeof payload?.detail === "string" ? payload.detail : "Bookkeeping request unavailable (" + code + ").";
  }
  async function request(path, options) {
    const headers = auth();
    if (!signedIn(headers)) {
      reset();
      throw new Error("Owner sign-in required. No accounting data requested.");
    }
    const response = await fetch(prefix + path, Object.assign({
      credentials: "same-origin", cache: "no-store", headers
    }, options || {}, {
      headers: Object.assign({}, headers, options?.headers || {})
    }));
    if (!response.ok) {
      let data = {};
      try { data = await response.json(); } catch (_) {}
      throw new Error(errorText(data, response.status));
    }
    return response;
  }
  async function refreshQueue(preferredId) {
    const response = await request("/review-queue?limit=50");
    const data = await response.json();
    queue = Array.isArray(data.jobs) ? data.jobs : [];
    select.replaceChildren(new Option("Choose a saved accounting job", ""));
    queue.forEach((job, index) => {
      const label = job.work_type + " · " + job.status + " · " + String(job.task_id || "").slice(0, 35);
      select.appendChild(new Option(label, String(index)));
    });
    const index = queue.findIndex(job => job.job_id === preferredId);
    selected = index >= 0 ? queue[index] : null;
    select.value = index >= 0 ? String(index) : "";
    if (selected) {
      update();
    } else {
      nextAction.textContent = queue.length
        ? "Choose an authorized accounting job to review."
        : "No authorized accounting review jobs available.";
    }
    message.textContent = queue.length
      ? queue.length + " authorized accounting job(s) available. Select one for owner review."
      : "No authorized bookkeeping jobs were returned. Feature flags or signed-consent records may be unavailable.";
    update();
  }
  async function perform(handler) {
    if (busy) return;
    setBusy(true);
    try { await handler(); }
    catch (err) {
      message.textContent = (err && err.message) || "Bookkeeping operation failed.";
      if (/sign-in|sign in|required|permission|consent|scope|disabled/i.test(message.textContent)) reset();
    } finally { setBusy(false); }
  }
  async function refreshTasks() {
    const response = await request("/eligible-tasks");
    const result = await response.json();
    availableTasks = Array.isArray(result.tasks) ? result.tasks : [];
    selectedTask = null;
    taskSelect.replaceChildren(new Option("Choose an authorized saved assignment", ""));
    availableTasks.forEach((item, index) => {
      taskSelect.appendChild(new Option(
        item.work_type + " · " + item.engagement_id + " / " + item.task_id, String(index)
      ));
    });
    byId("bookkeeping-engagement").value = "";
    byId("bookkeeping-task").value = "";
    message.textContent = availableTasks.length
      ? availableTasks.length + " eligible bookkeeping assignment(s). Choose a task."
      : "No authorized bookkeeping assignments. A verified signed agreement and active task are required.";
  }
  loadTasks.addEventListener("click", () => perform(refreshTasks));
  taskSelect.addEventListener("change", () => {
    const index = Number(taskSelect.value);
    selectedTask = taskSelect.value !== "" && Number.isInteger(index)
      ? (availableTasks[index] || null) : null;
    byId("bookkeeping-engagement").value = selectedTask ? selectedTask.engagement_id : "";
    byId("bookkeeping-task").value = selectedTask ? selectedTask.task_id : "";
    if (selectedTask) kind.value = selectedTask.work_type;
    synchronizeAsOf();
    lastSubmission = null;
  });
  load.addEventListener("click", () => perform(() => refreshQueue()));
  select.addEventListener("change", () => {
    const index = Number(select.value);
    selected = select.value !== "" && Number.isInteger(index) ? (queue[index] || null) : null;
    update();
  });
  status.addEventListener("click", () => perform(async () => {
    if (!selected) return;
    const id = selected.job_id;
    const result = await (await request("/jobs/" + encodeURIComponent(id))).json();
    message.textContent = "Status: " + result.status + ". Not delivered or paid.";
    await refreshQueue(id);
  }));
  download.addEventListener("click", () => perform(async () => {
    if (!selected) return;
    const response = await request("/jobs/" + encodeURIComponent(selected.job_id) + "/download");
    const file = await response.blob();
    if (file.size > 1000000) throw new Error("Unexpectedly large review file.");
    const url = URL.createObjectURL(file);
    try {
      const link = document.createElement("a");
      link.href = url;
      link.download = "nova-bookkeeping-owner-review.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      message.textContent = "Owner review copy downloaded. This is not client delivery.";
    } finally {
      window.setTimeout(() => URL.revokeObjectURL(url), 10000);
    }
  }));
  async function review(decision) {
    if (!selected) return;
    const id = selected.job_id;
    const response = await request("/jobs/" + encodeURIComponent(id) + "/review", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({approve: decision})
    });
    const result = await response.json();
    await refreshQueue(id);
    message.textContent = "Owner decision: " + result.status + ". No customer delivery or payment.";
  }
  approve.addEventListener("click", () => perform(() => review(true)));
  reject.addEventListener("click", () => perform(() => review(false)));
  recover.addEventListener("click", () => perform(async () => {
    if (!selected) return;
    const id = selected.job_id;
    const response = await request("/jobs/" + encodeURIComponent(id) + "/recover", {method: "POST"});
    const result = await response.json();
    await refreshQueue(id);
    message.textContent = result.status + ". No automatic retry. Owner review required.";
  }));
  function synchronizeAsOf() {
    asOf.required = kind.value !== "transaction_workpaper";
  }
  kind.addEventListener("change", synchronizeAsOf);
  synchronizeAsOf();
  submit.addEventListener("submit", event => {
    event.preventDefault();
    perform(async () => {
      const engagement = byId("bookkeeping-engagement").value.trim();
      const task = byId("bookkeeping-task").value.trim();
      const file = byId("bookkeeping-file").files[0];
      const type = kind.value;
      const date = asOf.value;
      if (!selectedTask || !availableTasks.includes(selectedTask) ||
          engagement !== selectedTask.engagement_id ||
          task !== selectedTask.task_id || type !== selectedTask.work_type || !file) {
        throw new Error("Choose a verified saved assignment and CSV first.");
      }
      if (!["transaction_workpaper", "receivables_aging", "payables_aging"].includes(type)) {
        throw new Error("Unsupported accounting work type.");
      }
      if (!file.name.toLowerCase().endsWith(".csv") || file.size < 1 || file.size > 1000000) {
        throw new Error("Choose a nonempty CSV no larger than 1 MB.");
      }
      if (type !== "transaction_workpaper" && !date) throw new Error("As-of date required.");
      const signature = [engagement, task, type, file.name, file.size, file.lastModified, date].join("|");
      if (!lastSubmission || lastSubmission.signature !== signature) {
        if (!window.crypto || typeof window.crypto.randomUUID !== "function")
          throw new Error("Secure request ID unavailable.");
        lastSubmission = {signature, key: window.crypto.randomUUID()};
      }
      const path = "/engagements/" + encodeURIComponent(engagement) +
        "/tasks/" + encodeURIComponent(task) + "/" + encodeURIComponent(type) + "/jobs";
      const headers = {
        "Content-Type": "text/csv", "X-Nova-File-Name": file.name,
        "Idempotency-Key": lastSubmission.key
      };
      if (date && type !== "transaction_workpaper") headers["X-Nova-As-Of"] = date;
      const response = await request(path, {method: "POST", body: file, headers});
      const result = await response.json();
      lastSubmission = null;
      message.textContent = "Review-only draft: " + result.status +
        (result.replayed ? " (saved request)" : "") + ". Nothing delivered.";
      await refreshQueue(result.job_id);
    });
  });
  reset();
})();