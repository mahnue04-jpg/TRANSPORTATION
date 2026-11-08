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
      description.textContent = entry.content_mode + " · " + (entry.channels || []).join(", ") +
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
  $("calendar-clear").addEventListener("click", clearForm);
  $("calendar-refresh").addEventListener("click", load);
  window.addEventListener("nova-studio-project-selected", function () {
    clearForm();
    load();
  });
  clearForm();
  load();
})();
