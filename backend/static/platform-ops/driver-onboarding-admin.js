(function () {
  const API = "/api/platform-ops/driver-onboarding";
  const banner = document.getElementById("banner");
  const listEl = document.getElementById("application-list");
  const detailEl = document.getElementById("detail-panel");
  let token = localStorage.getItem("amicor_access_token") || "";
  let selectedId = null;

  function showBanner(message, ok) {
    banner.textContent = message;
    banner.className = "banner " + (ok ? "ok" : "error");
    banner.classList.remove("hidden");
  }

  async function api(path, options) {
    if (!token) {
      const email = prompt("Admin email", "admin@amicor.local");
      const password = prompt("Password", "Amicor123!");
      const login = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const body = await login.json();
      if (!login.ok) throw new Error(body.detail || "Login failed");
      token = body.access_token;
      localStorage.setItem("amicor_access_token", token);
    }
    const headers = Object.assign({ Authorization: "Bearer " + token, "Content-Type": "application/json" }, options.headers || {});
    const response = await fetch(API + path, Object.assign({}, options, { headers }));
    const json = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(json.detail || response.statusText);
    return json;
  }

  function renderList(items) {
    listEl.innerHTML = "";
    if (!items.length) {
      listEl.innerHTML = "<p class='meta'>No applications found.</p>";
      return;
    }
    items.forEach((item) => {
      const div = document.createElement("div");
      div.className = "list-item" + (item.id === selectedId ? " active" : "");
      div.innerHTML = `
        <strong>${item.applicant_name || "Unnamed applicant"}</strong>
        <div class="meta">${item.email || ""} · ${item.mobile_phone || ""}</div>
        <div><span class="pill">${item.status}</span> · docs ${item.document_completion_percentage}%</div>
      `;
      div.addEventListener("click", () => loadDetail(item.id));
      listEl.appendChild(div);
    });
  }

  async function loadList() {
    const items = await api("/applications");
    renderList(items);
  }

  function actionButton(label, handler, secondary) {
    const btn = document.createElement("button");
    btn.textContent = label;
    if (secondary) btn.className = "secondary";
    btn.addEventListener("click", handler);
    return btn;
  }

  async function loadDetail(id) {
    selectedId = id;
    const app = await api(`/applications/${id}`);
    await loadList();
    const readiness = app.readiness || {};
    detailEl.innerHTML = "";
    const title = document.createElement("h2");
    title.textContent = `${app.legal_first_name || ""} ${app.legal_last_name || ""}`.trim() || "Application";
    detailEl.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = `Status: ${app.status} · License exp: ${app.license_expiration_date || "n/a"} · Driver ID: ${app.activated_driver_id || "not activated"}`;
    detailEl.appendChild(meta);

    const readinessBlock = document.createElement("pre");
    readinessBlock.textContent = JSON.stringify(readiness, null, 2);
    detailEl.appendChild(readinessBlock);

    const docs = document.createElement("div");
    docs.innerHTML = "<h3>Documents (metadata only)</h3>";
    if (!app.documents.length) docs.innerHTML += "<p class='meta'>No documents uploaded.</p>";
    app.documents.forEach((doc) => {
      const row = document.createElement("div");
      row.className = "meta";
      row.textContent = `${doc.category} · ${doc.review_status} · ${doc.original_filename || doc.status_only_value || "status-only"}`;
      docs.appendChild(row);
    });
    detailEl.appendChild(docs);

    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    toolbar.appendChild(actionButton("Move to under review", () => transition("under_review")));
    toolbar.appendChild(actionButton("Documents pending", () => transition("documents_pending"), true));
    toolbar.appendChild(actionButton("Background review", () => transition("background_review"), true));
    toolbar.appendChild(actionButton("Approve", () => decision("/approve")));
    toolbar.appendChild(actionButton("Activate driver", () => decision("/activate")));
    toolbar.appendChild(actionButton("Reject", () => decision("/reject"), true));
    detailEl.appendChild(toolbar);
  }

  async function transition(toStatus) {
    try {
      const confirmAction = ["rejected", "suspended", "approved", "activated"].includes(toStatus);
      await api(`/applications/${selectedId}/status`, {
        method: "POST",
        body: JSON.stringify({ to_status: toStatus, confirm: confirmAction, reason: "admin workspace" }),
      });
      showBanner(`Moved to ${toStatus}`, true);
      await loadDetail(selectedId);
    } catch (err) {
      showBanner(err.message, false);
    }
  }

  async function decision(path) {
    try {
      const reason = path.includes("reject") ? prompt("Rejection reason") : "";
      if (path.includes("reject") && !reason) return;
      const result = await api(`/applications/${selectedId}${path}`, {
        method: "POST",
        body: JSON.stringify({ confirm: true, reason: reason || undefined }),
      });
      showBanner(path.includes("activate") ? `Activated driver ${result.driver_id}` : "Updated", true);
      await loadDetail(selectedId);
    } catch (err) {
      showBanner(err.message, false);
    }
  }

  document.getElementById("refresh-list").addEventListener("click", () => loadList().catch((e) => showBanner(e.message, false)));
  loadList().catch((e) => showBanner(e.message, false));
})();
