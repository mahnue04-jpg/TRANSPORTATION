"use strict";

(function () {
  var state = { projectId: null, conversationId: null };
  var brainBusy = false;
  var preparedTransferId = null;
  var recorder = null;
  var recordingStream = null;
  var recordingBusy = false;
  function t(key, values) { key = String(key || ""); return window.NovaWorkspaceLanguage ? window.NovaWorkspaceLanguage.t(key, values) : key.replace(/\{(\w+)\}/g, function (_, name) { return values && values[name] !== undefined ? values[name] : "{" + name + "}"; }); }
  var projects = [];
  function speechLanguage() { return language() === "bilingual" ? "so" : language(); }
  function language() { return $("answer-language").value || "en"; }

  function selectProject(project, focus) {
    state.projectId = project ? project.workspace_id : null;
    state.conversationId = null;
    $("selected-project").textContent = project ? t("Selected project: {title}", {title: project.title}) : t("All workspace projects");
    $("transfer-project").value = state.projectId || "";
    $("ask-input").value = "";
    $("ask-input").placeholder = project ? t("Ask Nova to work on {title}", {title: project.title}) : t("Ask Mrs. Nova Brain about this workspace");
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
    return "<div class=\"item\"><strong>" + escapeHtml(t(hit.kind)) + "</strong> · " + title + "<div class=\"muted\">" + escapeHtml(hit.snippet) + "</div></div>";
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
      throw new Error(t("Network error. Saved work was not changed."));
    }
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (response.status === 401) throw new Error(t("Session expired. Sign in again."));
    if (response.status === 403) throw new Error(t("Access denied."));
    if (response.status === 404) throw new Error(t("Not found / unavailable."));
    if (response.status === 503 && path === "/api/nova/workspace/transcribe") throw new Error(t("Speech transcription is unavailable. Please type your request or try again."));
    if (response.status >= 500) throw new Error(t("Temporary system error."));
    if (!response.ok) throw new Error(errorText(body, t("Request failed.")));
    return body;
  }
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
    $("login-form").classList.add("hidden");
    var ident = identity();
    $("session-meta").textContent = on
      ? ((ident && (ident.name || ident.email)) || t("Signed in")) + " · Mrs. Nova Brain"
      : t("Sign in to use Nova Workspace.");
  }
  function renderDashboard(data) {
    projects = data.active_projects || [];
    $("transfer-project").innerHTML = "<option value=\"\">" + escapeHtml(t("Choose a project")) + "</option>" + projects.map(function (row) {
      return "<option value=\"" + escapeHtml(row.workspace_id) + "\">" + escapeHtml(row.title) + "</option>";
    }).join("");
    $("transfer-project").value = state.projectId || "";
    var selected = projects.find(function (row) { return row.workspace_id === state.projectId; });
    if (selected) {
      $("selected-project").textContent = t("Selected project: {title}", {title: selected.title});
      $("ask-input").placeholder = t("Ask Nova to work on {title}", {title: selected.title});
    }
    $("transfer-project-help").textContent = projects.length ? t("No file is required. Create a project first if this account has none.") : t("No projects in this signed-in account. Create a project below, or sign in to the account that owns your projects.");
    $("transfer-project").disabled = !projects.length;
    $("transfer-create-project").classList.toggle("hidden", !!projects.length);
    $("project-list").innerHTML = listHtml(data.active_projects, t("No active projects yet."), function (row) {
      return "<div class=\"item\"><button class=\"linkish\" data-open-project=\"" + escapeHtml(row.workspace_id) + "\">" +
        escapeHtml(row.title) + "</button><div class=\"muted\">" + escapeHtml(row.workspace_id) + " · " +
        escapeHtml(t(row.status)) + "</div></div>";
    });
    $("recent-work").innerHTML = listHtml(data.recent_work, t("No recent work yet."), function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong><div class=\"muted\">" +
        escapeHtml(t(row.kind)) + "</div></div>";
    });
    $("recent-conversations").innerHTML = listHtml(data.recent_conversations, t("No conversations yet."), function (row) {
      return "<div class=\"item\"><button class=\"linkish\" data-open-convo=\"" + escapeHtml(row.conversation_id) + "\">" +
        escapeHtml(row.title) + "</button><div class=\"muted\">" + escapeHtml(row.preview || t("Continue this thread")) + "</div></div>";
    });
    $("recent-files").innerHTML = listHtml(data.recent_files, t("No files yet."), function (row) {
      return "<div class=\"item\"><button class=\"linkish\" data-open-file=\"" + escapeHtml(row.file_id) + "\">" +
        escapeHtml(row.filename) + "</button><div class=\"muted\">" +
        escapeHtml(row.content_type || t("file")) + " · " + escapeHtml(row.created_at) + "</div></div>";
    });
    $("recent-searches").innerHTML = listHtml(data.saved_searches, t("Search above to save a search here."), function (row) {
      return "<div class=\"item\"><button class=\"linkish\" data-repeat-search=\"" + escapeHtml(row.query) + "\">" + escapeHtml(row.query) + "</button><div class=\"muted\">" + row.result_count + " " + t("results") + "</div></div>";
    });
    $("assistant-history").innerHTML = listHtml(data.assistant_history, t("Ask Nova to start your saved Workspace history."), function (row) {
      return "<div class=\"item\"><button class=\"linkish\" data-open-convo=\"" + escapeHtml(row.conversation_id) + "\">" + escapeHtml(t(row.role)) + " · " + t("Reopen conversation") + "</button><div class=\"muted\">" +
        escapeHtml((row.content || "").slice(0, 180)) + "</div></div>";
    });
  }
  async function refresh(preserveBrain) {
    if (!token()) {
      setSignedIn(false);
      $("brain-output").textContent = t("Mrs. Nova Brain is ready when you are signed in.");
      return;
    }
    setSignedIn(true);
    var data = await api("/api/nova/workspace/dashboard");
    renderDashboard(data);
    var transfers = await api("/api/nova/workspace/transfers");
    $("incoming-transfers").innerHTML = listHtml(transfers, t("No pending project copies for this account."), function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong> · " + escapeHtml(row.sender_email) +
        "<p>" + escapeHtml(t("Instructions + {conversations} conversations + {files} file texts. Expires {date}", {conversations: row.conversation_count, files: row.file_text_count, date: row.expires_at})) + "</p>" +
        "<button data-accept-transfer=\"" + escapeHtml(row.transfer_id) + "\">" + t("Accept and copy this project") + "</button></div>";
    });
    if (!preserveBrain) $("brain-output").textContent = t("Mrs. Nova Brain is connected to this Nova Workspace.");
  }
  async function runBrain(action, question) {
    if (recordingBusy) { showBanner(t("Finish recording and review the transcript before asking Nova.")); return; }
    if (brainBusy) return;
    if (!token()) {
      showBanner(t("Sign in to ask Mrs. Nova Brain."));
      $("login-form").classList.remove("hidden");
      return;
    }
    brainBusy = true;
    $("brain-output").setAttribute("aria-busy", "true");
    document.querySelectorAll("[data-brain], #ask-form button[type=submit]").forEach(function (button) { button.disabled = true; });
    showBanner(t("Nova is working on your request…"), true);
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
    $("brain-output").textContent = (result.fact_label || "AI SUGGESTION") + "\n\n" + (result.answer || t("No response from Mrs. Nova Brain."));
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
      $("search-results").innerHTML = listHtml(result.search.hits, t("No workspace matches."), renderSearchHit);
    }
    showBanner(t("Nova response is ready. Review the result below."), true);
    if (window.NovaWorkspaceSpeech) window.NovaWorkspaceSpeech.speak(result.answer || "");
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

    $("finish-somali").disabled = true;
  }
  $("record-somali").addEventListener("click", async function () {
    if (!token()) { showBanner(t("Sign in before recording speech.")); return; }
    if (!window.MediaRecorder || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      $("recording-status").textContent = t("Recording is unavailable in this browser. Type your request in Ask Nova."); return;
    }
    recordingBusy = true;
    if (window.NovaWorkspaceSpeech) window.NovaWorkspaceSpeech.stop();
    $("record-somali").disabled = true;
    $("recording-status").setAttribute("aria-busy", "true");
    try {
      recordingStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
      recorder = new MediaRecorder(recordingStream);
      var chunks = [];
      var bytes = 0;
      var sizeLimitReached = false;
      var recordedLanguage = speechLanguage();
      recorder.ondataavailable = function (event) {
        if (event.data.size) { chunks.push(event.data); bytes += event.data.size; }
        if (bytes >= 9000000 && recorder.state === "recording") { sizeLimitReached = true; recorder.stop(); }
      };
      recorder.onerror = function () { recordingBusy = false; $("recording-status").setAttribute("aria-busy", "false"); releaseMicrophone(); $("record-somali").disabled = false; $("recording-status").textContent = t("Recording failed. Try typing your request."); };
      recorder.onstop = async function () {
        releaseMicrophone();
        $("recording-status").textContent = t("Transcribing speech…");
        try {
          var form = new FormData();
          form.append("audio", new Blob(chunks, { type: recorder.mimeType || "audio/webm" }), "speech");
          form.append("language", recordedLanguage);
          var result = await api("/api/nova/workspace/transcribe", { method: "POST", body: form });
          var currentText = $("ask-input").value;
          $("ask-input").value = currentText ? currentText + "\n" + result.text : result.text;
          $("answer-language").value = recordedLanguage;
          $("answer-language").dispatchEvent(new Event("change"));
          $("ask-input").focus();
          $("recording-status").textContent = (sizeLimitReached ? t("Recording size limit reached. Your words were transcribed. ") : "") + t("Transcript ready. Review or correct the words, then press Ask Nova.");
        } catch (err) { $("recording-status").textContent = err.message; }
        finally {
          $("record-somali").disabled = false;
          $("recording-status").setAttribute("aria-busy", "false");
          recorder = null;
          recordingBusy = false;
        }
      };
      recorder.start(1000);
      $("finish-somali").disabled = false;
      $("recording-status").textContent = t("Recording. Press Finish when you are done.");
      // Silence and pauses never finish or submit a request. Finish is explicit.
      // The byte limit protects the existing 10 MB transcription endpoint.
    } catch (_) { recordingBusy = false; $("recording-status").setAttribute("aria-busy", "false"); releaseMicrophone(); $("record-somali").disabled = false; $("recording-status").textContent = t("Microphone could not start. Allow microphone access, or type your request."); }
  });
  window.NovaWorkspaceRecording = { isBusy: function () { return recordingBusy; }, finish: function () { if (recorder && recorder.state === "recording") recorder.stop(); } };
  $("finish-somali").addEventListener("click", function () { if (recorder && recorder.state === "recording") recorder.stop(); });
  window.addEventListener("pagehide", function () { if (recorder) recorder.onstop = null; releaseMicrophone(); });
  function updateAnswerLanguage() {
    var locales = {en: "en-US", so: "so-SO", ar: "ar-SA", fr: "fr-FR", es: "es-ES"};
    document.documentElement.setAttribute("data-nova-language", locales[speechLanguage()] || "en-US");
    $("ask-input").setAttribute("lang", speechLanguage());
    $("ask-input").setAttribute("dir", speechLanguage() === "ar" ? "rtl" : "ltr");
    if (window.NovaWorkspaceSpeech) window.NovaWorkspaceSpeech.stop();
  }
  $("answer-language").addEventListener("change", updateAnswerLanguage);
  $("screen-language").addEventListener("change", function () {
    window.NovaWorkspaceLanguage.setLanguage($("screen-language").value);
    $("answer-language").value = $("screen-language").value;
    updateAnswerLanguage();
    refresh(true).catch(function (err) { showBanner(err.message); });
  });
  if (window.NovaWorkspaceLanguage) {
    $("answer-language").value = window.NovaWorkspaceLanguage.current();
    updateAnswerLanguage();
  }
  $("transfer-create-project").addEventListener("click", function () {
    $("project-form").scrollIntoView({behavior: "smooth", block: "center"});
    $("project-title").focus();
  });
  $("transfer-project").addEventListener("change", function () {
    var selected = projects.find(function (row) { return row.workspace_id === $("transfer-project").value; });
    selectProject(selected || null, false);
  });
  $("transfer-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    if (!state.projectId) { showBanner(t("Select the project you want to copy first.")); return; }
    try {
      var result = await api("/api/nova/workspace/transfers", { method: "POST", body: JSON.stringify({
        workspace_id: state.projectId, recipient_email: $("transfer-email").value.trim(),
        include_conversations: $("transfer-conversations").checked,
        include_file_text: $("transfer-files").checked
      }) });
      $("transfer-preview").textContent = result.title + " → " + result.recipient_email + ": " + t(result.status) + ". " +
        t("Instructions + {conversations} conversations + {files} file texts. Recipient signs in and accepts under Incoming project copies. No email was sent.", {conversations: result.conversation_count, files: result.file_text_count});
      preparedTransferId = result.transfer_id;
      $("cancel-transfer").classList.toggle("hidden", result.status !== t("pending"));
      showBanner(t("Project copy prepared for recipient acceptance."), true);
    } catch (err) { showBanner(err.message); }
  });
  $("cancel-transfer").addEventListener("click", async function () {
    if (!preparedTransferId) return;
    try {
      await api("/api/nova/workspace/transfers/" + encodeURIComponent(preparedTransferId) + "/cancel", { method: "POST" });
      $("transfer-preview").textContent = t("Transfer canceled. The recipient cannot accept it.");
      $("cancel-transfer").classList.add("hidden");
    } catch (err) { showBanner(err.message); }
  });

  $("workspace-search-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var query = $("workspace-search").value.trim();
    if (query.length < 2) {
      showBanner(t("Enter at least 2 characters to search Nova Workspace."));
      return;
    }
    try {
      var data = await api("/api/nova/workspace/search?q=" + encodeURIComponent(query));
      $("search-results").innerHTML = listHtml(data.hits, t("No workspace matches."), renderSearchHit);
      showBanner(t("Searched Nova-owned workspace content only."), true);
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
      showBanner(t("Created project {id}.", {id: created.workspace_id}), true);
      await refresh(true);
    } catch (err) { showBanner(err.message); }
  });
  $("file-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var file = $("file-input").files[0];
    if (!file) {
      showBanner(t("Choose a file to upload with the existing /api/upload capability."));
      return;
    }
    try {
      var form = new FormData();
      form.append(t("file"), file);
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
      showBanner(t("Added {title} to Nova Workspace.", {title: associated.filename}), true);
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
          showBanner(t("Accepted project copy. You can now work on it in Ask Nova."), true);
        } finally { transferBtn.disabled = false; }
      }
      if (searchBtn) {
        $("workspace-search").value = searchBtn.getAttribute("data-repeat-search");
        $("workspace-search-form").requestSubmit();
      }
      if (projectBtn) {
        var project = await api("/api/nova/workspace/projects/" + encodeURIComponent(projectBtn.getAttribute("data-open-project")));
        selectProject(project, true);
        $("brain-output").textContent = "USER-SAVED INFORMATION\n\n" + project.title + "\n\n" + (project.description || t("No description saved."));
        showBanner(t("Selected {title}. Enter your request in Ask Nova.", {title: project.title}), true);
      }
      if (fileBtn) {
        var fileId = fileBtn.getAttribute("data-open-file");
        var fileRow = await api("/api/nova/workspace/files/" + encodeURIComponent(fileId));
        $("brain-output").textContent = "FILE: " + (fileRow.filename || fileId) + "\n\n" +
          (fileRow.excerpt || t("No readable text was extracted from this file."));
        showBanner(t("Opened saved file {id}.", {id: fileId}), true);
      }
      if (convoBtn) {
        var convo = await api("/api/nova/workspace/conversations/" + encodeURIComponent(convoBtn.getAttribute("data-open-convo")));
        var openedId = convo.conversation_id;
        var linkedProject = convo.workspace_id ? await api("/api/nova/workspace/projects/" + encodeURIComponent(convo.workspace_id)) : null;
        selectProject(linkedProject, true);
        state.conversationId = openedId;
        $("brain-output").textContent = (convo.messages || []).map(function (row) {
          return row.role + ": " + row.content;
        }).join("\n") || t("Continue this Mrs. Nova Brain thread.");
        showBanner(t("Continuing conversation {id}.", {id: state.conversationId}), true);
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
      showBanner(errorText(payload, t("Sign-in failed")));
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
    showBanner(t("Signed in. Nova Workspace is available."), true);
  });
  $("sign-out").addEventListener("click", async function () {
    if (session() && session().logout) await session().logout();
    window.location.href = "/nova/workspace";
  });
})();
