"use strict";

(function () {
  var state = { projectId: null, conversationId: null };

  function $(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function organizationId() { return session() && session().getOrganizationId ? session().getOrganizationId() : null; }
  function identity() {
    var current = session() && session().getCurrent ? session().getCurrent() : null;
    return current && current.identity ? current.identity : null;
  }
  function showBanner(message, ok) {
    var el = $("banner");
    el.textContent = message;
    el.classList.remove("hidden");
    el.classList.toggle("ok", !!ok);
  }
  function errorText(payload, fallback) {
    if (!payload) return fallback;
    if (typeof payload.detail === "string") return payload.detail;
    return fallback;
  }
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function listHtml(items, empty, render) {
    if (!items || !items.length) return empty;
    return items.map(render).join("");
  }
  async function api(path, options) {
    var headers = {};
    var opts = options || {};
    if (!(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
    if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
    else if (token()) headers.Authorization = "Bearer " + token();
    var response = await fetch(path, Object.assign({}, opts, { headers: headers }));
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (response.status === 401) throw new Error("Session expired. Sign in to continue.");
    if (!response.ok) throw new Error(errorText(body, "Request failed (" + response.status + ")"));
    return body;
  }
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
    $("login-form").classList.add("hidden");
    var ident = identity();
    $("session-meta").textContent = on
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · Mrs. Nova Brain"
      : "Sign in to use Nova Workspace.";
  }
  function renderDashboard(data) {
    $("project-list").innerHTML = listHtml(data.active_projects, "No active projects yet.", function (row) {
      return "<div class=\"item\"><button class=\"linkish\" data-open-project=\"" + escapeHtml(row.workspace_id) + "\">" +
        escapeHtml(row.title) + "</button><div class=\"muted\">" + escapeHtml(row.workspace_id) + " · " +
        escapeHtml(row.status) + "</div></div>";
    });
    $("recent-work").innerHTML = listHtml(data.recent_work, "No recent work yet.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong><div class=\"muted\">" +
        escapeHtml(row.kind) + "</div></div>";
    });
    $("recent-conversations").innerHTML = listHtml(data.recent_conversations, "No conversations yet.", function (row) {
      return "<div class=\"item\"><button class=\"linkish\" data-open-convo=\"" + escapeHtml(row.conversation_id) + "\">" +
        escapeHtml(row.title) + "</button><div class=\"muted\">" + escapeHtml(row.preview || "Continue this thread") + "</div></div>";
    });
    $("recent-files").innerHTML = listHtml(data.recent_files, "No files yet.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.filename) + "</strong><div class=\"muted\">" +
        escapeHtml(row.content_type || "file") + " · " + escapeHtml(row.created_at) + "</div></div>";
    });
    $("recent-searches").innerHTML = listHtml(data.saved_searches, "No searches yet.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.query) + "<div class=\"muted\">" + row.result_count + " results</div></div>";
    });
    $("assistant-history").innerHTML = listHtml(data.assistant_history, "No assistant history loaded.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.role) + "</strong><div class=\"muted\">" +
        escapeHtml((row.content || "").slice(0, 180)) + "</div></div>";
    });
  }
  async function refresh() {
    if (!token()) {
      setSignedIn(false);
      $("brain-output").textContent = "Mrs. Nova Brain is ready when you are signed in.";
      return;
    }
    setSignedIn(true);
    var data = await api("/api/nova/workspace/dashboard");
    renderDashboard(data);
    $("brain-output").textContent = "Mrs. Nova Brain is connected to this Nova Workspace.";
  }
  async function runBrain(action, question) {
    if (!token()) {
      showBanner("Sign in to ask Mrs. Nova Brain.");
      $("login-form").classList.remove("hidden");
      return;
    }
    var result = await api("/api/nova/workspace/ask", {
      method: "POST",
      body: JSON.stringify({
        action: action,
        question: question || $("ask-input").value.trim(),
        workspace_id: state.projectId,
        conversation_id: state.conversationId
      })
    });
    state.conversationId = result.conversation_id || state.conversationId;
    $("brain-output").textContent = result.answer || "No response from Mrs. Nova Brain.";
    if (result.search) {
      $("search-results").innerHTML = listHtml(result.search.hits, "No workspace matches.", function (hit) {
        return "<div class=\"item\"><strong>" + escapeHtml(hit.kind) + "</strong> · " +
          escapeHtml(hit.title) + "<div class=\"muted\">" + escapeHtml(hit.snippet) + "</div></div>";
      });
    }
    showBanner("Mrs. Nova Brain used existing Nova intelligence APIs.", true);
    await refresh();
  }

  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message); });

  $("workspace-search-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var query = $("workspace-search").value.trim();
    if (query.length < 2) {
      showBanner("Enter at least 2 characters to search Nova Workspace.");
      return;
    }
    try {
      var data = await api("/api/nova/workspace/search?q=" + encodeURIComponent(query));
      $("search-results").innerHTML = listHtml(data.hits, "No workspace matches.", function (hit) {
        return "<div class=\"item\"><strong>" + escapeHtml(hit.kind) + "</strong> · " +
          escapeHtml(hit.title) + "<div class=\"muted\">" + escapeHtml(hit.snippet) + "</div></div>";
      });
      showBanner("Searched Nova-owned workspace content only.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("ask-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try { await runBrain("ask"); } catch (err) { showBanner(err.message); }
  });
  document.querySelectorAll("[data-brain]").forEach(function (button) {
    button.addEventListener("click", async function () {
      try { await runBrain(button.getAttribute("data-brain")); } catch (err) { showBanner(err.message); }
    });
  });
  $("project-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      var created = await api("/api/nova/workspace/projects", {
        method: "POST",
        body: JSON.stringify({
          title: $("project-title").value.trim(),
          description: $("project-description").value.trim()
        })
      });
      state.projectId = created.workspace_id;
      $("project-title").value = "";
      $("project-description").value = "";
      showBanner("Created Nova Workspace project " + created.workspace_id + ".", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("file-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var file = $("file-input").files[0];
    if (!file) {
      showBanner("Choose a file to upload with the existing /api/upload capability.");
      return;
    }
    try {
      var form = new FormData();
      form.append("file", file);
      var uploaded = await api("/api/upload", { method: "POST", body: form });
      var associated = await api("/api/nova/workspace/files", {
        method: "POST",
        body: JSON.stringify({
          filename: uploaded.filename || file.name,
          content_type: uploaded.content_type || file.type,
          size_bytes: uploaded.size_bytes || file.size,
          excerpt: uploaded.extracted_text || uploaded.document_summary || "",
          workspace_id: state.projectId || null
        })
      });
      showBanner("Added " + associated.filename + " to Nova Workspace.", true);
      $("file-input").value = "";
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  document.addEventListener("click", async function (event) {
    var projectBtn = event.target.closest("[data-open-project]");
    var convoBtn = event.target.closest("[data-open-convo]");
    try {
      if (projectBtn) {
        state.projectId = projectBtn.getAttribute("data-open-project");
        await api("/api/nova/workspace/projects/" + encodeURIComponent(state.projectId));
        showBanner("Opened project " + state.projectId + ".", true);
      }
      if (convoBtn) {
        state.conversationId = convoBtn.getAttribute("data-open-convo");
        var convo = await api("/api/nova/workspace/conversations/" + encodeURIComponent(state.conversationId));
        $("brain-output").textContent = (convo.messages || []).map(function (row) {
          return row.role + ": " + row.content;
        }).join("\n") || "Continue this Mrs. Nova Brain thread.";
        showBanner("Continuing conversation " + state.conversationId + ".", true);
      }
    } catch (err) { showBanner(err.message); }
  });
  $("sign-in-toggle").addEventListener("click", function () {
    $("login-form").classList.toggle("hidden");
  });
  $("login-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: $("login-email").value, password: $("login-password").value })
    });
    var payload = await response.json();
    if (!response.ok) {
      showBanner(errorText(payload, "Sign-in failed"));
      return;
    }
    if (session() && session().start) {
      session().start({
        userId: payload.user_id,
        email: payload.email,
        name: payload.display_name,
        role: payload.role,
        accessToken: payload.access_token,
        refreshToken: payload.refresh_token,
        organizationId: payload.organization_id,
        organization_name: payload.organization_name,
        authorizedRoles: payload.authorized_roles
      });
    }
    await refresh();
    showBanner("Signed in. Nova Workspace is available.", true);
  });
  $("sign-out").addEventListener("click", async function () {
    if (session() && session().logout) await session().logout();
    window.location.href = "/nova/workspace";
  });
})();
