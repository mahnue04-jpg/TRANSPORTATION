"use strict";

(function () {
  var state = { projectId: null, conversationId: null };
  var brainBusy = false;
  var preparedTransferId = null;
  var recorder = null;
  var recordingStream = null;
  var recordingTimer = null;
  function language() { return $("answer-language").value || "en"; }

  function selectProject(project, focus) {
    state.projectId = project ? project.workspace_id : null;
    state.conversationId = null;
    $("selected-project").textContent = project ? "Selected project: " + project.title : "All workspace projects";
    $("ask-input").value = "";
    $("ask-input").placeholder = project ? "Ask Nova to work on " + project.title : "Ask Mrs. Nova Brain about this workspace";
    if (focus) {
      $("workspace-command").scrollIntoView({ behavior: "smooth", block: "start" });
      $("ask-input").focus({ preventScroll: true });
    }
  }

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
  function renderSearchHit(hit) {
    var attribute = { project: "data-open-project", conversation: "data-open-convo", file: "data-open-file" }[hit.kind];
    var title = attribute ? "<button class=\"linkish\" " + attribute + "=\"" + escapeHtml(hit.id) + "\">" + escapeHtml(hit.title) + "</button>" : escapeHtml(hit.title);
    return "<div class=\"item\"><strong>" + escapeHtml(hit.kind) + "</strong> · " + title + "<div class=\"muted\">" + escapeHtml(hit.snippet) + "</div></div>";
  }
  async function api(path, options) {
    var headers = {};
    var opts = options || {};
    if (!(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
    if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
    else if (token()) headers.Authorization = "Bearer " + token();
    var response;
    try {
      response = await fetch(path, Object.assign({}, opts, { headers: headers }));
    } catch (_) {
      throw new Error("Network error. Saved work was not changed.");
    }
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (response.status === 401) throw new Error("Session expired. Sign in again.");
    if (response.status === 403) throw new Error("Access denied.");
    if (response.status === 404) throw new Error("Not found / unavailable.");
    if (response.status >= 500) throw new Error("Temporary system error.");
    if (!response.ok) throw new Error(errorText(body, "Request failed."));
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
      return "<div class=\"item\"><button class=\"linkish\" data-open-file=\"" + escapeHtml(row.file_id) + "\">" +
        escapeHtml(row.filename) + "</button><div class=\"muted\">" +
        escapeHtml(row.content_type || "file") + " · " + escapeHtml(row.created_at) + "</div></div>";
    });
    $("recent-searches").innerHTML = listHtml(data.saved_searches, "Search above to save a search here.", function (row) {
      return "<div class=\"item\"><button class=\"linkish\" data-repeat-search=\"" + escapeHtml(row.query) + "\">" + escapeHtml(row.query) + "</button><div class=\"muted\">" + row.result_count + " results</div></div>";
    });
    $("assistant-history").innerHTML = listHtml(data.assistant_history, "Ask Nova to start your saved Workspace history.", function (row) {
      return "<div class=\"item\"><button class=\"linkish\" data-open-convo=\"" + escapeHtml(row.conversation_id) + "\">" + escapeHtml(row.role) + " · Reopen conversation</button><div class=\"muted\">" +
        escapeHtml((row.content || "").slice(0, 180)) + "</div></div>";
    });
  }
  async function refresh(preserveBrain) {
    if (!token()) {
      setSignedIn(false);
      $("brain-output").textContent = "Mrs. Nova Brain is ready when you are signed in.";
      return;
    }
    setSignedIn(true);
    var data = await api("/api/nova/workspace/dashboard");
    renderDashboard(data);
    var transfers = await api("/api/nova/workspace/transfers");
    $("incoming-transfers").innerHTML = listHtml(transfers, "No pending project copies for this account.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong> from " + escapeHtml(row.sender_email) +
        "<p>Instructions + " + row.conversation_count + " conversations + " + row.file_text_count + " file texts. Expires " + escapeHtml(row.expires_at) + "</p>" +
        "<button data-accept-transfer=\"" + escapeHtml(row.transfer_id) + "\">Accept and copy this project</button></div>";
    });
    if (!preserveBrain) $("brain-output").textContent = "Mrs. Nova Brain is connected to this Nova Workspace.";
  }
  async function runBrain(action, question) {
    if (brainBusy) return;
    if (!token()) {
      showBanner("Sign in to ask Mrs. Nova Brain.");
      $("login-form").classList.remove("hidden");
      return;
    }
    brainBusy = true;
    $("brain-output").setAttribute("aria-busy", "true");
    document.querySelectorAll("[data-brain], #ask-form button[type=submit]").forEach(function (button) { button.disabled = true; });
    showBanner("Nova is working on your request…", true);
    try {
    var result = await api("/api/nova/workspace/ask", {
      method: "POST",
      body: JSON.stringify({
        action: action,
        answer_language: language(),
        question: question !== undefined ? question : (action === "ask" ? $("ask-input").value.trim() : null),
        workspace_id: state.projectId,
        conversation_id: state.conversationId
      })
    });
    state.conversationId = result.conversation_id || state.conversationId;
    $("brain-output").textContent = (result.fact_label || "AI SUGGESTION") + "\n\n" + (result.answer || "No response from Mrs. Nova Brain.");
    (result.sources || []).concat(result.source_href ? [{title: "Open Work & Revenue", url: result.source_href}] : []).forEach(function (source) {
      if (!/^https?:\/\//i.test(source.url || "") && source.url !== "/nova/work") return;
      var link = document.createElement("a");
      link.href = source.url;
      link.textContent = source.title || source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      $("brain-output").appendChild(document.createElement("br"));
      $("brain-output").appendChild(link);
    });
    if (result.search) {
      $("search-results").innerHTML = listHtml(result.search.hits, "No workspace matches.", renderSearchHit);
    }
    showBanner("Nova response is ready. Review the result below.", true);
    await refresh(true);
    } finally {
      brainBusy = false;
      $("brain-output").setAttribute("aria-busy", "false");
      document.querySelectorAll("[data-brain], #ask-form button[type=submit]").forEach(function (button) { button.disabled = false; });
    }
  }

  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message); });
  function releaseMicrophone() {
    if (recordingStream) recordingStream.getTracks().forEach(function (track) { track.stop(); });
    recordingStream = null;
    clearTimeout(recordingTimer);
    $("finish-somali").disabled = true;
  }
  $("record-somali").addEventListener("click", async function () {
    if (!token()) { showBanner("Sign in before recording speech."); return; }
    if (!window.MediaRecorder || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      $("recording-status").textContent = "Recording is unavailable in this browser. You can type Somali in Ask Nova."; return;
    }
    $("record-somali").disabled = true;
    try {
      recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder = new MediaRecorder(recordingStream);
      var chunks = [];
      var startingText = $("ask-input").value;
      recorder.ondataavailable = function (event) { if (event.data.size) chunks.push(event.data); };
      recorder.onerror = function () { releaseMicrophone(); $("record-somali").disabled = false; $("recording-status").textContent = "Recording failed. Try typing Somali."; };
      recorder.onstop = async function () {
        releaseMicrophone();
        $("recording-status").textContent = "Transcribing Somali…";
        try {
          var form = new FormData();
          form.append("audio", new Blob(chunks, { type: recorder.mimeType }), "speech");
          var result = await api("/api/nova/workspace/transcribe", { method: "POST", body: form });
          $("ask-input").value = $("ask-input").value === startingText ? result.text : $("ask-input").value + "\n" + result.text;
          $("answer-language").value = "so";
          $("answer-language").dispatchEvent(new Event("change"));
          $("ask-input").focus();
          $("recording-status").textContent = "Somali transcript is ready. Review or correct the words, then press Ask Nova. / Hubi qoraalka, kadib guji Ask Nova.";
        } catch (err) { $("recording-status").textContent = err.message + " You can type Somali instead."; }
        finally { $("record-somali").disabled = false; }
      };
      recorder.start();
      $("finish-somali").disabled = false;
      $("recording-status").textContent = "Recording Somali. Press Finish when you are done. / Ku hadal Af-Soomaali.";
      recordingTimer = setTimeout(function () { if (recorder.state === "recording") recorder.stop(); }, 60000);
    } catch (_) { releaseMicrophone(); $("record-somali").disabled = false; $("recording-status").textContent = "Microphone could not start. Allow microphone access, or type Somali."; }
  });
  $("finish-somali").addEventListener("click", function () { if (recorder && recorder.state === "recording") recorder.stop(); });
  window.addEventListener("pagehide", function () { if (recorder) recorder.onstop = null; releaseMicrophone(); });
  $("answer-language").addEventListener("change", function () {
    document.documentElement.setAttribute("data-nova-language", language() === "en" ? "en-US" : "so-SO");
    $("ask-input").setAttribute("lang", language() === "en" ? "en" : "so");
  });
  $("transfer-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    if (!state.projectId) { showBanner("Select the project you want to copy first."); return; }
    try {
      var result = await api("/api/nova/workspace/transfers", { method: "POST", body: JSON.stringify({
        workspace_id: state.projectId, recipient_email: $("transfer-email").value.trim(),
        include_conversations: $("transfer-conversations").checked,
        include_file_text: $("transfer-files").checked
      }) });
      $("transfer-preview").textContent = result.title + " → " + result.recipient_email + ": " + result.status +
        ". Instructions, " + result.conversation_count + " conversations and " + result.file_text_count + " file texts. Recipient signs in and accepts under Incoming project copies. No email was sent.";
      preparedTransferId = result.transfer_id;
      $("cancel-transfer").classList.toggle("hidden", result.status !== "pending");
      showBanner("Project copy prepared for recipient acceptance.", true);
    } catch (err) { showBanner(err.message); }
  });
  $("cancel-transfer").addEventListener("click", async function () {
    if (!preparedTransferId) return;
    try {
      await api("/api/nova/workspace/transfers/" + encodeURIComponent(preparedTransferId) + "/cancel", { method: "POST" });
      $("transfer-preview").textContent = "Transfer canceled. The recipient cannot accept it.";
      $("cancel-transfer").classList.add("hidden");
    } catch (err) { showBanner(err.message); }
  });

  $("workspace-search-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var query = $("workspace-search").value.trim();
    if (query.length < 2) {
      showBanner("Enter at least 2 characters to search Nova Workspace.");
      return;
    }
    try {
      var data = await api("/api/nova/workspace/search?q=" + encodeURIComponent(query));
      $("search-results").innerHTML = listHtml(data.hits, "No workspace matches.", renderSearchHit);
      showBanner("Searched Nova-owned workspace content only.", true);
      await refresh(true);
      $("search-results-card").scrollIntoView({ behavior: "smooth", block: "start" });
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
      selectProject(created, true);
      $("project-title").value = "";
      $("project-description").value = "";
      showBanner("Created Nova Workspace project " + created.workspace_id + ".", true);
      await refresh(true);
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
      await refresh(true);
    } catch (err) { showBanner(err.message); }
  });
  document.addEventListener("click", async function (event) {
    var transferBtn = event.target.closest("[data-accept-transfer]");
    var searchBtn = event.target.closest("[data-repeat-search]");
    var projectBtn = event.target.closest("[data-open-project]");
    var convoBtn = event.target.closest("[data-open-convo]");
    var fileBtn = event.target.closest("[data-open-file]");
    try {
      if (transferBtn) {
        transferBtn.disabled = true;
        try {
          var accepted = await api("/api/nova/workspace/transfers/" + encodeURIComponent(transferBtn.getAttribute("data-accept-transfer")) + "/accept", { method: "POST" });
          var copied = await api("/api/nova/workspace/projects/" + encodeURIComponent(accepted.destination_workspace_id));
          selectProject(copied, true);
          $("brain-output").textContent = "USER-SAVED INFORMATION\n\n" + copied.title + "\n\n" + (copied.description || "");
          await refresh(true);
          showBanner("Accepted project copy. You can now work on it in Ask Nova.", true);
        } finally { transferBtn.disabled = false; }
      }
      if (searchBtn) {
        $("workspace-search").value = searchBtn.getAttribute("data-repeat-search");
        $("workspace-search-form").requestSubmit();
      }
      if (projectBtn) {
        var project = await api("/api/nova/workspace/projects/" + encodeURIComponent(projectBtn.getAttribute("data-open-project")));
        selectProject(project, true);
        $("brain-output").textContent = "USER-SAVED INFORMATION\n\n" + project.title + "\n\n" + (project.description || "No description saved.");
        showBanner("Selected " + project.title + ". Enter your request in Ask Nova.", true);
      }
      if (fileBtn) {
        var fileId = fileBtn.getAttribute("data-open-file");
        var fileRow = await api("/api/nova/workspace/files/" + encodeURIComponent(fileId));
        $("brain-output").textContent = "FILE: " + (fileRow.filename || fileId) + "\n\n" +
          (fileRow.excerpt || "No readable text was extracted from this file.");
        showBanner("Opened saved Workspace file " + fileId + ".", true);
      }
      if (convoBtn) {
        var convo = await api("/api/nova/workspace/conversations/" + encodeURIComponent(convoBtn.getAttribute("data-open-convo")));
        var openedId = convo.conversation_id;
        var linkedProject = convo.workspace_id ? await api("/api/nova/workspace/projects/" + encodeURIComponent(convo.workspace_id)) : null;
        selectProject(linkedProject, true);
        state.conversationId = openedId;
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
