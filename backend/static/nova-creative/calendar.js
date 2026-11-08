(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var bridge = window.NovaCreativeCalendarBridge;
  if (!bridge || !$("calendar-form")) return;

  var loadedProject = null;
  var entries = [];
  var revision = 0;
  var busy = false;
  var localTime = function (iso) {
    var date = new Date(iso);
    if (!Number.isFinite(date.getTime())) return "";
    var local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  };
  function feedback(message, error) {
    var el = $("calendar-feedback");
    el.textContent = message;
    el.style.color = error ? "#9b1c1c" : "";
  }
  function basePath(projectId) {
    return "/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/calendar";
  }
  function clearForm() {
    $("calendar-form").reset();
    $("calendar-edit-id").value = "";
    $("calendar-save").textContent = "Save video plan";
    $("calendar-date").value = localTime(new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString());
    $("calendar-duration").value = "30";
  }
  function active() { return bridge.selectedProject(); }
  function requestProject() {
    var projectId = active();
    if (!projectId) {
      feedback("Select a Creative Studio project first.", true);
      return null;
    }
    return projectId;
  }
  function button(label, action, entry) {
    var el = document.createElement("button");
    el.type = "button";
    el.className = "secondary";
    el.textContent = label;
    el.addEventListener("click", function () { action(entry); });
    return el;
  }
  function render() {
    var list = $("calendar-list");
    list.replaceChildren();
    if (!loadedProject) {
      list.textContent = "Select a project to view its calendar.";
      return;
    }
    if (!entries.length) {
      list.textContent = "No video plans yet. Create your first plan above.";
      return;
    }
    entries.forEach(function (entry) {
      var article = document.createElement("article");
      article.className = "card";
      var title = document.createElement("h4");
      title.textContent = entry.topic;
      article.appendChild(title);
      var description = document.createElement("p");
      description.className = "hint";
      var when = new Date(entry.scheduled_at);
      description.textContent = entry.content_mode + " · " + Math.round((entry.duration_seconds || 30) / 60 * 10) / 10 + " min · " + (entry.channels || []).join(", ") +
        " · " + (Number.isFinite(when.getTime()) ? when.toLocaleString() : "Unknown time") +
        " · " + entry.status;
      article.appendChild(description);
      var actions = document.createElement("div");
      actions.className = "actions wrap";
      actions.appendChild(button("Edit", edit, entry));
      if (entry.status !== "approved" && entry.status !== "canceled") {
        actions.appendChild(button("Approve script", approve, entry));
      }
      if (entry.status === "approved") {
        actions.appendChild(button("Prepare in Studio", prepare, entry));
        if ((entry.content_mode === "faceless" || entry.content_mode === "education") && entry.duration_seconds === 30) {
          actions.appendChild(button("Render preview MP4", renderPreview, entry));
        }
        if (entry.duration_seconds >= 120 && entry.duration_seconds <= 600) {
          actions.appendChild(button("Assemble saved clips", assembleSelect, entry));
        }
      }
      if (entry.status !== "canceled") actions.appendChild(button("Cancel plan", cancel, entry));
      article.appendChild(actions);
      list.appendChild(article);
    });
  }
  async function load() {
    var project = active();
    loadedProject = project;
    var current = ++revision;
    $("calendar-project-status").textContent = project ?
      "Selected project: " + project + " · Planning only; no automatic posting" :
      "Select a Creative Studio project to manage your content calendar.";
    if (!project) {
      entries = [];
      render();
      return;
    }
    $("calendar-list").textContent = "Loading content plans...";
    try {
      var result = await bridge.api(basePath(project), { method: "GET" });
      if (current !== revision || active() !== project) return;
      entries = result.entries || [];
      render();
      feedback("Calendar loaded. No posts have been published.");
    } catch (err) {
      if (current !== revision) return;
      entries = [];
      render();
      feedback(err.message || "Could not load calendar.", true);
    }
  }
  function edit(entry) {
    if (entry.status === "canceled") {
      feedback("This entry is canceled. Create a new plan instead.", true);
      return;
    }
    $("calendar-edit-id").value = entry.id;
    $("calendar-topic").value = entry.topic || "";
    $("calendar-script").value = entry.script || "";
    $("calendar-mode").value = entry.content_mode || "faceless";
    $("calendar-duration").value = String(entry.duration_seconds || 30);
    $("calendar-date").value = localTime(entry.scheduled_at);
    document.querySelectorAll('input[name="calendar-channel"]').forEach(function (box) {
      box.checked = (entry.channels || []).includes(box.value);
    });
    $("calendar-save").textContent = "Save plan changes";
    $("calendar-topic").focus();
    feedback("Editing plan. Save changes to update the calendar.");
  }
  async function mutate(entry, patch, action) {
    var project = requestProject();
    if (!project || busy) return;
    var originalRevision = revision;
    busy = true;
    try {
      await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) +
        (action === "cancel" ? "/cancel" : ""), {
        method: action === "cancel" ? "POST" : "PATCH",
        ...(action === "cancel" ? {} : { body: JSON.stringify(patch) })
      });
      if (active() !== project || originalRevision !== revision) return;
      clearForm();
      feedback(action === "cancel" ? "Plan canceled." : "Script approved for planning; publishing is still disabled.");
      await load();
    } catch (err) { feedback(err.message || "Unable to update entry.", true); }
    finally { busy = false; }
  }
  function approve(entry) {
    if (!String(entry.script || "").trim()) {
      edit(entry);
      feedback("Add a reviewed script and save it before approving.", true);
      return;
    }
    mutate(entry, { status: "approved" }, "approve");
  }
  async function assembleSelect(entry) {
    var project = requestProject();
    if (!project || busy) return;
    feedback("Loading saved video clips for assembly...");
    try {
      var detail = await bridge.api("/api/nova/creative/projects/" + encodeURIComponent(project), { method: "GET" });
      if (active() !== project) return;
      var videos = (detail.assets || []).filter(function (asset) {
        return asset.kind === "video" && asset.url && asset.media_available !== false &&
          asset.id && !(asset.metadata || {}).assembly_signature;
      });
      if (videos.length < 2) {
        feedback("Save at least two finished video clips in this project before assembling. No generation was started.", true);
        return;
      }
      var host = $("calendar-assembly");
      host.replaceChildren();
      var header = document.createElement("h4");
      header.textContent = "Select clips in playback order for: " + entry.topic;
      host.appendChild(header);
      var explain = document.createElement("p");
      explain.className = "hint";
      explain.textContent = "Choose 2–16 existing saved videos. Click Add in sequence; their combined length should match your planned duration. Each must have H.264 video and AAC audio. No paid generation.";
      host.appendChild(explain);
      var ordered = [];
      var sequence = document.createElement("ol");
      host.appendChild(sequence);
      function showOrder() {
        sequence.replaceChildren();
        ordered.forEach(function (asset, index) {
          var row = document.createElement("li");
          row.textContent = (index + 1) + ". " + (asset.title || asset.id);
          row.appendChild(button("Remove", function () {
            ordered.splice(index, 1);
            showOrder();
          }, asset));
          sequence.appendChild(row);
        });
      }
      videos.forEach(function (asset) {
        var line = document.createElement("div");
        line.className = "actions wrap";
        var label = document.createElement("span");
        var duration = (asset.metadata || {}).duration_seconds;
        label.textContent = (asset.title || asset.id) + (duration ? " · " + Math.round(duration) + "s" : "");
        line.appendChild(label);
        line.appendChild(button("Add to sequence", function () {
          if (ordered.some(function (item) { return item.id === asset.id; })) {
            feedback("That clip is already selected.", true);
            return;
          }
          if (ordered.length >= 16) {
            feedback("Maximum 16 clips in this first assembly mode.", true);
            return;
          }
          ordered.push(asset);
          showOrder();
        }, asset));
        host.appendChild(line);
      });
      host.appendChild(button("Build combined MP4", async function () {
        if (ordered.length < 2 || busy) {
          feedback("Choose at least two clips first.", true);
          return;
        }
        if (active() !== project) return;
        busy = true;
        feedback("Combining existing clips into one video. This may take time; do not start a second assembly.");
        try {
          var result = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) + "/assemble", {
            method: "POST",
            body: JSON.stringify({ asset_ids: ordered.map(function (item) { return item.id; }) })
          });
          if (active() !== project) return;
          if (result.status !== "ASSEMBLED_REVIEW_REQUIRED") throw new Error("No completed MP4 was confirmed.");
          feedback("Combined MP4 saved. Review and download it from Studio's Asset list.");
          host.replaceChildren();
          if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
        } catch (err) {
          feedback(err.message || "Assembly failed; saved source clips were preserved.", true);
        } finally { busy = false; }
      }, entry));
      host.scrollIntoView({ behavior: "smooth", block: "start" });
      feedback("Choose clips in the correct order and build the combined video.");
    } catch (err) {
      feedback(err.message || "Unable to load saved videos.", true);
    }
  }

  async function renderPreview(entry) {
    var project = requestProject();
    if (!project || busy) return;
    busy = true;
    var currentRevision = revision;
    feedback("Rendering local 30-second video preview. No paid provider is used.");
    try {
      var result = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) + "/render-preview", {
        method: "POST"
      });
      if (active() !== project || currentRevision !== revision) return;
      if (!result || result.status !== "PREVIEW_RENDERED" || !result.download_url) {
        throw new Error("No verified preview MP4 was returned.");
      }
      feedback("Preview MP4 saved to this project. Open Asset list to review/download. Publishing is disabled.");
      if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
    } catch (err) {
      feedback(err.message || "Preview rendering failed. Your reviewed plan was preserved.", true);
    } finally { busy = false; }
  }
  function cancel(entry) {
    if (window.confirm("Cancel this planned video? It will not be posted.")) {
      mutate(entry, {}, "cancel");
    }
  }
  async function prepare(entry) {
    var project = requestProject();
    if (!project || busy) return;
    var currentRevision = revision;
    busy = true;
    feedback("Saving the approved script and narration text into Creative Studio...");
    try {
      var result = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) + "/prepare", {
        method: "POST"
      });
      if (active() !== project || currentRevision !== revision) return;
      if (!result || result.status !== "PREPARED_TEXT_ONLY") {
        throw new Error("Studio did not confirm production-text preparation.");
      }
      feedback(result.reused ?
        "Existing reviewed script, narration and caption assets are ready in Studio." :
        "Reviewed script, narration and caption source saved in Studio. Generate the video separately after reviewing settings.");
      if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
    } catch (err) {
      feedback(err.message || "Unable to prepare Studio content.", true);
    } finally {
      busy = false;
    }
  }
  $("calendar-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var project = requestProject();
    if (!project || busy) return;
    var datetime = new Date($("calendar-date").value);
    if (!Number.isFinite(datetime.getTime())) {
      feedback("Enter a valid planned date and time.", true);
      return;
    }
    var payload = {
      topic: $("calendar-topic").value.trim(),
      script: $("calendar-script").value.trim(),
      content_mode: $("calendar-mode").value,
      duration_seconds: Number($("calendar-duration").value),
      channels: Array.from(document.querySelectorAll('input[name="calendar-channel"]:checked')).map(function (node) { return node.value; }),
      scheduled_at: datetime.toISOString()
    };
    if (!payload.topic) { feedback("Enter a video topic.", true); return; }
    var entryId = $("calendar-edit-id").value;
    var current = revision;
    busy = true;
    $("calendar-save").disabled = true;
    try {
      await bridge.api(basePath(project) + (entryId ? "/" + encodeURIComponent(entryId) : ""), {
        method: entryId ? "PATCH" : "POST", body: JSON.stringify(payload)
      });
      if (active() !== project || current !== revision) return;
      clearForm();
      feedback("Video plan saved. No generation or posting has started.");
      await load();
    } catch (err) { feedback(err.message || "Unable to save plan.", true); }
    finally { busy = false; $("calendar-save").disabled = false; }
  });
  $("studio-guide-help").addEventListener("click", function () {
    var request = $("studio-guide-request").value.trim();
    var topic = $("calendar-topic").value.trim() || request;
    var seconds = Number($("calendar-duration").value);
    var mode = $("calendar-mode").value;
    var words = Math.round(seconds / 60 * 130);
    var sections = Math.max(2, Math.ceil(seconds / 60));
    var result = $("studio-guide-response");
    if (!topic) {
      result.textContent = "Tell me the subject of your video or enter a video topic above.";
      return;
    }
    var guidance = [
      "Nova Studio Guide — production outline (not AI-generated footage)",
      "Subject: " + topic,
      "Format: " + mode + " • Target duration: " + Math.round(seconds / 60 * 10) / 10 + " minutes",
      "Suggested script size: approximately " + words + " spoken words.",
      "Suggested structure: introduction, " + sections + " planned story/lesson beats, and a closing.",
      "1. Draft the story, lesson, or narration in the Script field.",
      "2. Divide it into logical sections and review the complete storyline.",
      "3. Save the plan, then approve the exact reviewed script.",
      "4. Prepare in Studio to store narration and caption source text.",
      seconds === 30 && (mode === "faceless" || mode === "education")
        ? "5. A local 30-second title-card preview is available after approval."
        : "5. Long-form or presenter/video-scene rendering is not yet connected; don't expect a complete MP4 from this plan.",
      "6. Review final footage, audio, captions, rights, and costs before any future publishing.",
      "This guide is an initial deterministic planning helper. Conversational AI assistance remains a separate integration milestone."
    ];
    result.textContent = guidance.join("\n");
  });
  $("calendar-clear").addEventListener("click", clearForm);
  $("calendar-refresh").addEventListener("click", load);
  window.addEventListener("nova-studio-project-selected", function () {
    clearForm();
    load();
  });
  clearForm();
  load();
})();
