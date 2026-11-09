(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var bridge = window.NovaCreativeCalendarBridge;
  if (!bridge || !$("calendar-form")) return;

  var loadedProject = null;
  var entries = [];
  var revision = 0;
  var busy = false;
  var studioAssistantHistory = [];
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
        if ((entry.content_mode === "faceless" || entry.content_mode === "education") &&
            entry.duration_seconds >= 15 && entry.duration_seconds <= 120 &&
            Array.isArray(entry.storyboard) && entry.storyboard.length > 0) {
          actions.appendChild(button("Render storyboard preview", renderStoryboardPreview, entry));
          actions.appendChild(button("Assemble saved scenes", assembleStoryboardScenes, entry));
        }
        if ((entry.content_mode === "faceless" || entry.content_mode === "education") && entry.duration_seconds === 30) {
          actions.appendChild(button("Render preview MP4", renderPreview, entry));
        }
        if (entry.duration_seconds >= 120 && entry.duration_seconds <= 600) {
          actions.appendChild(button("Assemble saved clips", assembleSelect, entry));
        }
      }
      if (entry.duration_seconds >= 120 && entry.duration_seconds <= 600) {
        actions.appendChild(button("Assembly job status", async function (selected) {
          var project = requestProject();
          if (!project) return;
          try {
            var info = await bridge.api(basePath(project) + "/" +
              encodeURIComponent(selected.id) + "/assembly-status", { method: "GET" });
            feedback(info.message || ("Saved assembly: " + info.status));
            if (info.status === "GENERATED" && typeof bridge.refreshProductionAssets === "function") {
              await bridge.refreshProductionAssets();
            }
          } catch (err) { feedback(err.message || "Could not retrieve assembly status.", true); }
        }, entry));
      }
      if (entry.status !== "canceled" && entry.duration_seconds >= 120 && entry.duration_seconds <= 600) {
        if (entry.status !== "approved") actions.appendChild(button("Edit saved timeline", assembleSelect, entry));
      }
      if (entry.status !== "canceled" && entry.duration_seconds >= 120) {
        actions.appendChild(button("Edit chapters", editChapters, entry));
      }
      if (entry.status === "approved" && entry.duration_seconds >= 600 &&
          entry.duration_seconds <= 7200 && (entry.chapters || []).length >= 2) {
        actions.appendChild(button("Export chapter master", exportMaster, entry));
        actions.appendChild(button("Resume failed export", resumeMaster, entry));
        actions.appendChild(button("Master job status", async function (selected) {
          var project = requestProject();
          if (!project) return;
          try {
            var info = await bridge.api(basePath(project) + "/" +
              encodeURIComponent(selected.id) + "/master-status", { method: "GET" });
            var step = info.checkpoint && info.checkpoint.stage;
            feedback((info.message || ("Master export: " + info.status)) + (step ? " Last saved stage: " + step.replace(/_/g, " ").toLowerCase() + "." : ""));
            if (info.status === "GENERATED" && typeof bridge.refreshProductionAssets === "function") {
              await bridge.refreshProductionAssets();
            }
          } catch (err) { feedback(err.message || "Could not retrieve master export status.", true); }
        }, entry));
      }
      if (entry.duration_seconds >= 600) {
        actions.appendChild(button("Review saved master versions", reviewMasterVersions, entry));
      }
      if (entry.status !== "canceled") actions.appendChild(button("Edit storyboard", editStoryboard, entry));
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
      var selector = $("studio-assistant-entry");
      var previous = selector.value;
      selector.replaceChildren(new Option("Select a saved plan", ""));
      entries.forEach(function (item) {
        selector.add(new Option(item.topic + " (" + Math.round(item.duration_seconds / 60 * 10) / 10 + " min)", item.id));
      });
      if (entries.some(function (item) { return item.id === previous; })) selector.value = previous;
      else {
        studioAssistantHistory = [];
        $("studio-assistant-conversation").textContent = "";
      }
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
  async function resumeMaster(entry) {
    var project = requestProject();
    if (!project || busy) return;
    busy = true;
    try {
      var status = await bridge.api(basePath(project) + "/" +
        encodeURIComponent(entry.id) + "/master-status", { method: "GET" });
      if (active() !== project) return;
      if (status.status === "GENERATED") {
        feedback("The master was already saved. Open the Studio Asset list to review it.");
        if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
        return;
      }
      if (status.status !== "ERROR" || !status.resumable) {
        feedback(status.message || "Only a confirmed failed export is eligible for resume; interrupted work must be reviewed.", true);
        return;
      }
      if (!window.confirm("Resume this confirmed failed export? Verified chapters and saved segments will be reused. No paid provider is used.")) return;
      var result = await bridge.api(basePath(project) + "/" +
        encodeURIComponent(entry.id) + "/resume-master-job", { method: "POST" });
      if (active() !== project) return;
      if (result.status === "ALREADY_COMPLETED") {
        feedback("A verified completed master was recovered; nothing was rerendered.");
        if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
      } else if (result.status === "QUEUED") {
        feedback("Export resumed from saved verified segments. Use Master job status to track progress.");
      } else {
        feedback(result.message || "Resume was not started. Check the saved job status.", true);
      }
    } catch (err) {
      feedback(err.message || "Resume was not started; saved chapters were preserved.", true);
    } finally { busy = false; }
  }

  async function reviewMasterVersions(entry) {
    var project = requestProject();
    if (!project || busy) return;
    var host = $("calendar-chapters");
    host.replaceChildren();
    var heading = document.createElement("h3");
    heading.textContent = "Finished master review — " + entry.topic;
    host.appendChild(heading);
    var message = document.createElement("p");
    message.className = "hint";
    message.textContent = "Verified saved masters are listed separately. Reviewing an MP4 does not authorize publishing or commercial use.";
    host.appendChild(message);
    try {
      var result = await bridge.api(basePath(project) + "/" +
        encodeURIComponent(entry.id) + "/master-versions", {method: "GET"});
      if (active() !== project || !host.contains(heading)) return;
      var masters = result.masters || [];
      if (!masters.length) {
        var none = document.createElement("p");
        none.textContent = "No verified saved final masters yet. Complete the chapter exports first.";
        host.appendChild(none);
        return;
      }
      masters.forEach(function (master, index) {
        var panel = document.createElement("fieldset");
        var legend = document.createElement("legend");
        legend.textContent = "Saved master " + (index + 1);
        panel.appendChild(legend);
        var info = document.createElement("p");
        info.textContent = "Saved " + (master.created_at || "unknown date") +
          " · " + Math.round((Number(master.duration_seconds) || 0) / 60) +
          " minutes · version " + String(master.pinned_version_sha256 || "legacy").slice(0, 12);
        panel.appendChild(info);
        var video = document.createElement("video");
        video.controls = true;
        video.preload = "metadata";
        video.playsInline = true;
        video.style.maxWidth = "100%";
        video.style.maxHeight = "360px";
        video.setAttribute("aria-label", "Saved verified master video");
        var loaded = false;
        var safeForMemory = Number.isFinite(Number(master.file_size_bytes)) &&
          Number(master.file_size_bytes) > 0 &&
          Number(master.file_size_bytes) <= 128 * 1024 * 1024;
        if (safeForMemory && typeof bridge.fetchProtectedVideo === "function") {
          panel.appendChild(button("Load verified master for playback", async function () {
            if (active() !== project) return;
            try {
              var blob = await bridge.fetchProtectedVideo(project, master.asset_id);
              if (active() !== project || !host.contains(panel)) return;
              if (video.dataset.objectUrl) URL.revokeObjectURL(video.dataset.objectUrl);
              var url = URL.createObjectURL(blob);
              video.dataset.objectUrl = url;
              video.src = url;
              if (!panel.contains(video)) panel.appendChild(video);
              loaded = true;
              feedback("Verified master loaded. Review the actual footage, narration and captions before marking quality checks.");
            } catch (err) { feedback(err.message || "Protected master playback failed.", true); }
          }, master));
          panel.appendChild(button("Download reviewed MP4", async function () {
            if (active() !== project || typeof bridge.downloadProtectedAsset !== "function") return;
            try {
              await bridge.downloadProtectedAsset(master.download_url,
                "creative-studio-master-" + master.asset_id + ".mp4");
              feedback("Protected master download requested.");
            } catch (err) { feedback(err.message || "Master download could not be completed.", true); }
          }, master));
        } else {
          var largeNotice = document.createElement("p");
          largeNotice.className = "hint";
          largeNotice.textContent = "Large or unknown-size MP4: in-browser playback is disabled to protect memory. Download to review with your video player.";
          panel.appendChild(largeNotice);
        }
        if (typeof bridge.streamProtectedMaster === "function") {
          panel.appendChild(button("Save full MP4 to computer (streaming)", async function () {
            if (active() !== project) return;
            try {
              // Trigger the browser file picker directly from the click.
              var saved = await bridge.streamProtectedMaster(project, master.asset_id);
              if (active() !== project) return;
              feedback("Saved " + Math.round(saved.bytes / (1024 * 1024)) +
                " MiB to your computer. Review the exported video before approval.");
            } catch (err) {
              feedback(err.message || "Streaming MP4 save could not be completed.", true);
            }
          }, master));
        }
        var localReviewLabel = document.createElement("label");
        var localReviewCheckbox = document.createElement("input");
        localReviewCheckbox.type = "checkbox";
        localReviewLabel.appendChild(localReviewCheckbox);
        localReviewLabel.appendChild(document.createTextNode(
          " I opened and watched this complete saved MP4 in a local player (or loaded it above)."
        ));
        panel.appendChild(localReviewLabel);
        var checks = [
          ["footage_ok", "Full footage reviewed"],
          ["audio_ok", "Narration and audio continuity reviewed"],
          ["captions_ok", "Captions reviewed"],
          ["continuity_ok", "Chapter transitions and ending reviewed"],
          ["rights_reviewed", "Licensing and asset permissions reviewed"]
        ];
        var controls = {};
        checks.forEach(function (field) {
          var label = document.createElement("label");
          var box = document.createElement("input");
          box.type = "checkbox";
          box.checked = Boolean(master.review && master.review[field[0]]);
          controls[field[0]] = box;
          label.appendChild(box);
          label.appendChild(document.createTextNode(" " + field[1]));
          panel.appendChild(label);
        });
        var correctionCategoryLabel = document.createElement("label");
        correctionCategoryLabel.textContent = "Main issue";
        var correctionCategory = document.createElement("select");
        [["general", "General"], ["footage", "Footage"], ["audio", "Narration / audio"],
         ["captions", "Captions"], ["continuity", "Chapter continuity"],
         ["rights", "Rights and licensing"]].forEach(function (option) {
          correctionCategory.add(new Option(option[1], option[0]));
        });
        correctionCategory.value = master.review && master.review.correction_category || "general";
        correctionCategoryLabel.appendChild(correctionCategory);
        panel.appendChild(correctionCategoryLabel);
        var correctionChapterLabel = document.createElement("label");
        correctionChapterLabel.textContent = "Affected chapter of this saved master (optional)";
        var correctionChapter = document.createElement("select");
        correctionChapter.add(new Option("General master issue", ""));
        for (var chapterNumber = 0; chapterNumber < Number(master.chapter_count || 0); chapterNumber++) {
          correctionChapter.add(new Option("Chapter " + (chapterNumber + 1), String(chapterNumber)));
        }
        correctionChapter.value = master.review && master.review.correction_chapter_index != null
          ? String(master.review.correction_chapter_index) : "";
        correctionChapterLabel.appendChild(correctionChapter);
        panel.appendChild(correctionChapterLabel);
        var noteLabel = document.createElement("label");
        noteLabel.textContent = "Review or correction notes";
        var notes = document.createElement("textarea");
        notes.rows = 3;
        notes.maxLength = 2000;
        notes.value = master.review && master.review.notes || "";
        noteLabel.appendChild(notes);
        panel.appendChild(noteLabel);
        var state = document.createElement("p");
        state.setAttribute("role", "status");
        state.textContent = master.review ? "Saved review: " + master.review.status :
          "Not reviewed.";
        panel.appendChild(state);
        panel.appendChild(button("Save master quality review", async function () {
          if (!loaded && !localReviewCheckbox.checked) {
            state.textContent = "Review this saved master in the player or download and watch the full MP4 before submitting the checklist.";
            return;
          }
          var body = {
            notes: notes.value, correction_category: correctionCategory.value,
            correction_chapter_index: correctionChapter.value === "" ? null : Number(correctionChapter.value)
          };
          checks.forEach(function (field) { body[field[0]] = controls[field[0]].checked; });
          try {
            var response = await bridge.api(basePath(project) + "/" +
              encodeURIComponent(entry.id) + "/masters/" +
              encodeURIComponent(master.asset_id) + "/review", {
                method: "PUT", body: JSON.stringify(body)
              });
            if (active() !== project || !host.contains(panel)) return;
            state.textContent = "Saved: " + response.status +
              ". Commercial and publishing approvals remain separate.";
            feedback(response.message || "Master review saved.");
          } catch (err) {
            state.textContent = err.message || "Master review could not be saved.";
          }
        }, master));
        var correctionButton = button("Open affected chapter correction", async function () {
          if (active() !== project) return;
          try {
            var plan = await bridge.api(basePath(project) + "/" +
              encodeURIComponent(entry.id) + "/masters/" +
              encodeURIComponent(master.asset_id) + "/correction-plan", {method: "GET"});
            if (active() !== project || !host.contains(panel)) return;
            if (!plan.can_open_current_editor) {
              feedback("The affected chapter is no longer in the current plan. Compare versions before making changes.", true);
              return;
            }
            if (!plan.current_plan_matches_reviewed_chapter &&
                !window.confirm("This chapter has changed since the reviewed master. Open the current chapter editor without changing it automatically?")) return;
            await editChapters(entry);
            if (active() !== project) return;
            var selectedPanel = $("calendar-chapters").querySelector(
              '[data-chapter-index="' + plan.chapter_index + '"]');
            if (selectedPanel) {
              selectedPanel.scrollIntoView({behavior: "smooth", block: "start"});
              var input = selectedPanel.querySelector("input");
              if (input) input.focus({preventScroll: true});
            }
            feedback(plan.message + " Chapter " + (plan.chapter_index + 1) +
              " needs review: " + (plan.notes || "No correction notes provided."));
          } catch (err) {
            feedback(err.message || "Save a changes-required review and affected chapter first.", true);
          }
        }, master);
        panel.appendChild(correctionButton);
        var assistantCorrection = button("Ask Nova to prepare chapter correction brief", async function () {
          if (busy || active() !== project) return;
          busy = true;
          try {
            var proposal = await bridge.api(basePath(project) + "/" +
              encodeURIComponent(entry.id) + "/masters/" +
              encodeURIComponent(master.asset_id) +
              "/assistant/chapter-revision-proposal", {method: "POST"});
            if (active() !== project || !host.contains(panel)) return;
            if (!proposal || proposal.status !== "DRAFT_CHAPTER_REVISION" ||
                !Number.isInteger(proposal.chapter_index) ||
                proposal.chapter_index < 0 || proposal.chapter_index >= (entry.chapters || []).length) {
              throw new Error("Nova did not return a valid chapter correction.");
            }
            var drafts = (entry.chapters || []).map(function (chapter) {
              return {
                title: chapter.title, duration_seconds: chapter.duration_seconds,
                asset_ids: (chapter.asset_ids || []).slice(),
                revision_note: chapter.revision_note || ""
              };
            });
            drafts[proposal.chapter_index].revision_note = proposal.proposed_chapter.revision_note;
            await editChapters(entry, drafts);
            if (active() !== project) return;
            var selectedPanel = $("calendar-chapters").querySelector(
              '[data-chapter-index="' + proposal.chapter_index + '"]');
            if (selectedPanel) {
              selectedPanel.scrollIntoView({behavior: "smooth", block: "start"});
              var field = selectedPanel.querySelector("textarea");
              if (field) field.focus({preventScroll: true});
            }
            feedback("Nova opened an unsaved chapter revision brief. Review it and edit the actual clips before saving; no video was changed.");
          } catch (err) {
            feedback(err.message || "Nova could not prepare this chapter brief.", true);
          } finally { busy = false; }
        }, master);
        panel.appendChild(assistantCorrection);
        host.appendChild(panel);
      });
      host.scrollIntoView({behavior: "smooth", block: "start"});
    } catch (err) {
      message.textContent = err.message || "Unable to load verified master versions.";
      feedback(message.textContent, true);
    }
  }

  async function exportMaster(entry) {
    var project = requestProject();
    if (!project || busy) return;
    if (!window.confirm("Start a review-only chapter master export? Videos over 60 minutes require the owner's extended-export configuration, private storage, and ample disk space. All existing chapters remain saved. No paid provider or publishing will be activated.")) return;
    busy = true;
    feedback("Submitting master export as a saved job...");
    try {
      var result = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) +
        "/export-master-job", { method: "POST" });
      if (active() !== project) return;
      if (result.status !== "QUEUED" && result.status !== "ALREADY_RUNNING") {
        throw new Error(result.message || "No saved export job was confirmed.");
      }
      feedback("Master export queued. You may return to this project and check its status.");
      // The job is persisted server-side; this short poll is only for convenience.
      for (var attempt = 0; attempt < 90 && active() === project; attempt++) {
        await new Promise(function (resolve) { setTimeout(resolve, 3000); });
        var status = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) +
          "/master-status", { method: "GET" });
        if (status.status === "GENERATED") {
          feedback("Master MP4 saved. Review and download from the Studio Asset list.");
          if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
          return;
        }
        if (status.status === "ERROR" || status.status === "INTERRUPTED_UNCONFIRMED") {
          feedback(status.message || "Master export needs attention. Saved chapters are preserved.", true);
          return;
        }
        var stage = status.checkpoint && status.checkpoint.stage;
        feedback("Master export: " + status.status + (stage ? " · " + stage.replace(/_/g, " ").toLowerCase() : "") + ". Completed chapters remain saved.");
      }
      feedback("Master export is still processing or its status is not confirmed. Reopen the project and check status.");
    } catch (err) {
      feedback(err.message || "Master export could not be confirmed; original chapters remain saved.", true);
    } finally { busy = false; }
  }

  async function editStoryboard(entry, suggestedScenes) {
    var project = requestProject();
    if (!project) return;
    var visualAssets = [];
    var renderedPreviews = [];
    try {
      var projectDetail = await bridge.api("/api/nova/creative/projects/" + encodeURIComponent(project), {
        method: "GET"
      });
      if (active() !== project) return;
      visualAssets = (projectDetail.assets || []).filter(function (asset) {
        return asset.kind === "image" && Boolean(asset.url) && asset.status === "GENERATED";
      });
      renderedPreviews = (projectDetail.assets || []).filter(function (asset) {
        var meta = asset.metadata || {};
        return asset.kind === "video" && asset.status === "GENERATED" &&
          meta.pipeline === "calendar_storyboard_preview" &&
          meta.calendar_entry_id === entry.id && Boolean(asset.url);
      });
    } catch (err) {
      feedback("Image choices unavailable; scene text can still be edited.", true);
    }
    var host = $("calendar-storyboard");
    var rows = (Array.isArray(suggestedScenes) ? suggestedScenes : (entry.storyboard || [])).map(function (scene) {
      return {
        heading: scene.heading || "",
        visual_note: scene.visual_note || "",
        revision_note: scene.revision_note || "",
        narration: scene.narration || "",
        duration_seconds: Number(scene.duration_seconds) || 1,
        visual_asset_id: scene.visual_asset_id || null,
        transition: scene.transition === "fade" ? "fade" : "cut",
        caption_cues: (scene.caption_cues || []).map(function (cue) {
          return { start_seconds: Number(cue.start_seconds), end_seconds: Number(cue.end_seconds), text: String(cue.text || "") };
        })
      };
    });
    host.replaceChildren();
    var title = document.createElement("h3");
    title.textContent = "Storyboard — " + entry.topic;
    host.appendChild(title);
    var note = document.createElement("p");
    note.className = "hint";
    note.textContent = "Edit each scene and review timing. Nothing is saved until you click Save storyboard. This is production planning, not generated footage.";
    host.appendChild(note);
    // This rehearsal reads unsaved editor state, without simulating spoken audio.
    var rehearsal = document.createElement("fieldset");
    var rehearsalLegend = document.createElement("legend");
    rehearsalLegend.textContent = "Review scene and caption timing";
    rehearsal.appendChild(rehearsalLegend);
    var rehearsalHelp = document.createElement("p");
    rehearsalHelp.className = "hint";
    rehearsalHelp.textContent = "Scrub the timeline to inspect which caption would appear. Speech-level synchronization still requires audio review.";
    rehearsal.appendChild(rehearsalHelp);
    var playheadLabel = document.createElement("label");
    playheadLabel.textContent = "Storyboard position (seconds)";
    var playhead = document.createElement("input");
    playhead.type = "range";
    playhead.min = "0";
    playhead.max = String(entry.duration_seconds);
    playhead.step = "0.1";
    playhead.value = "0";
    playheadLabel.appendChild(playhead);
    rehearsal.appendChild(playheadLabel);
    var rehearsalStatus = document.createElement("p");
    rehearsalStatus.setAttribute("role", "status");
    rehearsalStatus.setAttribute("aria-live", "polite");
    rehearsal.appendChild(rehearsalStatus);
    var rehearsalNarration = document.createElement("p");
    rehearsal.appendChild(rehearsalNarration);
    var rehearsalCaption = document.createElement("p");
    rehearsal.appendChild(rehearsalCaption);
    host.appendChild(rehearsal);
    var videoPanel = document.createElement("div");
    var video = document.createElement("video");
    video.controls = true;
    video.preload = "metadata";
    video.playsInline = true;
    video.setAttribute("aria-label", "Previously rendered storyboard preview with narration");
    video.style.maxWidth = "100%";
    video.style.maxHeight = "360px";
    var previewHelp = document.createElement("p");
    previewHelp.className = "hint";
    previewHelp.textContent = "Playback is from the most recently saved storyboard preview. Unsaved script, voice or caption edits are NOT in that MP4 until you save, reapprove and render again.";
    videoPanel.appendChild(previewHelp);
    if (renderedPreviews.length && typeof bridge.fetchProtectedVideo === "function") {
      var latestPreview = renderedPreviews.slice().sort(function (a, b) {
        return String(b.created_at || "").localeCompare(String(a.created_at || ""));
      })[0];
      var audioButton = button("Load saved video with narration", async function () {
        if (active() !== project) return;
        audioButton.disabled = true;
        try {
          var blob = await bridge.fetchProtectedVideo(project, latestPreview.id);
          if (active() !== project || !host.contains(audioButton)) return;
          if (video.dataset.objectUrl) URL.revokeObjectURL(video.dataset.objectUrl);
          var objectUrl = URL.createObjectURL(blob);
          video.dataset.objectUrl = objectUrl;
          video.src = objectUrl;
          if (!videoPanel.contains(video)) videoPanel.appendChild(video);
          video.addEventListener("emptied", function () {
            if (!video.src && video.dataset.objectUrl) {
              URL.revokeObjectURL(video.dataset.objectUrl);
              delete video.dataset.objectUrl;
            }
          }, { once: true });
          feedback("Saved video loaded. Play or scrub to review the actual narration against caption timing.");
        } catch (err) {
          feedback(err.message || "Protected preview playback unavailable.", true);
        } finally { audioButton.disabled = false; }
      }, entry);
      videoPanel.appendChild(audioButton);
      var reviewPanel = document.createElement("fieldset");
      var reviewTitle = document.createElement("legend");
      reviewTitle.textContent = "Quality review of this saved MP4";
      reviewPanel.appendChild(reviewTitle);
      var reviewHint = document.createElement("p");
      reviewHint.className = "hint";
      reviewHint.textContent = "Review only after loading and watching this video. The checkboxes do not approve commercial rights or publishing.";
      reviewPanel.appendChild(reviewHint);
      var reviewChecks = [
        ["narration_ok", "Narration sounds correct and complete"],
        ["captions_ok", "Caption text and timing reviewed"],
        ["visuals_ok", "Visuals and transitions reviewed"],
        ["playback_ok", "Playback and audio continue to the end"]
      ];
      var controls = {};
      var previousReview = (latestPreview.metadata || {}).storyboard_preview_review || {};
      reviewChecks.forEach(function (field) {
        var label = document.createElement("label");
        var check = document.createElement("input");
        check.type = "checkbox";
        check.checked = Boolean(previousReview[field[0]]);
        controls[field[0]] = check;
        label.appendChild(check);
        label.appendChild(document.createTextNode(" " + field[1]));
        reviewPanel.appendChild(label);
      });
      var notesLabel = document.createElement("label");
      notesLabel.textContent = "Correction notes (optional)";
      var notes = document.createElement("textarea");
      notes.rows = 3;
      notes.maxLength = 2000;
      notes.value = previousReview.notes || "";
      notesLabel.appendChild(notes);
      reviewPanel.appendChild(notesLabel);
      var categoryLabel = document.createElement("label");
      categoryLabel.textContent = "Main correction area";
      var categorySelect = document.createElement("select");
      [["general", "General"], ["narration", "Narration"], ["captions", "Captions"], ["visuals", "Visuals"], ["playback", "Playback"]].forEach(function (option) {
        categorySelect.add(new Option(option[1], option[0]));
      });
      categorySelect.value = previousReview.correction_category || "general";
      categoryLabel.appendChild(categorySelect);
      reviewPanel.appendChild(categoryLabel);
      var targetLabel = document.createElement("label");
      targetLabel.textContent = "Scene needing correction (optional)";
      var sceneSelect = document.createElement("select");
      sceneSelect.add(new Option("General video issue", ""));
      rows.forEach(function (scene, index) {
        sceneSelect.add(new Option("Scene " + (index + 1) + " — " + scene.heading, String(index)));
      });
      sceneSelect.value = previousReview.correction_scene_index == null
        ? "" : String(previousReview.correction_scene_index);
      targetLabel.appendChild(sceneSelect);
      reviewPanel.appendChild(targetLabel);
      var jumpToCorrection = button("Go to correction scene", function () {
        if (sceneSelect.value === "") {
          feedback("Select a scene to jump to, or use the general video review.", true);
          return;
        }
        var index = Number(sceneSelect.value);
        var sceneFields = list.querySelectorAll("fieldset");
        if (!Number.isInteger(index) || index < 0 || index >= rows.length || !sceneFields[index]) {
          feedback("The selected scene is no longer available. Reload the storyboard.", true);
          return;
        }
        var position = rows.slice(0, index).reduce(function (sum, item) {
          return sum + Math.max(0, Number(item.duration_seconds) || 0);
        }, 0);
        playhead.value = String(position);
        if (video.src && Number.isFinite(video.duration) && video.duration > 0) {
          video.currentTime = Math.min(position, video.duration);
          video.pause();
        }
        rehearse();
        sceneFields[index].scrollIntoView({behavior: "smooth", block: "start"});
        var firstInput = sceneFields[index].querySelector("input, textarea, select");
        if (firstInput) firstInput.focus({preventScroll: true});
      }, entry);
      reviewPanel.appendChild(jumpToCorrection);
      var proposalButton = button("Ask Nova to prepare correction brief", async function () {
        if (active() !== project || busy) return;
        busy = true;
        proposalButton.disabled = true;
        try {
          var result = await bridge.api(basePath(project) + "/" +
            encodeURIComponent(entry.id) + "/assistant/previews/" +
            encodeURIComponent(latestPreview.id) + "/revision-proposal", {method: "POST"});
          if (active() !== project || !host.contains(reviewPanel)) return;
          if (!result || result.status !== "DRAFT_SUGGESTION" ||
              !Number.isInteger(result.scene_index) ||
              !rows[result.scene_index]) throw new Error("No supported scene correction returned.");
          rows[result.scene_index].revision_note = result.suggested_scene.revision_note;
          renderRows();
          sceneSelect.value = String(result.scene_index);
          jumpToCorrection.click();
          feedback("Correction brief copied to the editable scene. Review it, make changes, and save the storyboard. No media was modified.");
        } catch (err) {
          feedback(err.message || "Save a changes-required review with a specific scene and correction notes first.", true);
        } finally {
          busy = false;
          proposalButton.disabled = false;
        }
      }, entry);
      reviewPanel.appendChild(proposalButton);
      var scriptProposal = document.createElement("fieldset");
      var scriptLegend = document.createElement("legend");
      scriptLegend.textContent = "Proposed narration correction (not saved)";
      scriptProposal.appendChild(scriptLegend);
      var originalScript = document.createElement("p");
      var proposedScript = document.createElement("textarea");
      proposedScript.rows = 4;
      proposedScript.maxLength = 6000;
      proposedScript.setAttribute("aria-label", "Editable proposed narration");
      var scriptMessage = document.createElement("p");
      scriptMessage.className = "hint";
      scriptProposal.appendChild(originalScript);
      scriptProposal.appendChild(proposedScript);
      scriptProposal.appendChild(scriptMessage);
      var preparedSceneIndex = null;
      var scriptSuggestionButton = button("Suggest exact wording correction", async function () {
        if (active() !== project || busy) return;
        busy = true;
        scriptSuggestionButton.disabled = true;
        try {
          var result = await bridge.api(basePath(project) + "/" +
            encodeURIComponent(entry.id) + "/assistant/previews/" +
            encodeURIComponent(latestPreview.id) + "/script-revision", {method: "POST"});
          if (active() !== project || !host.contains(reviewPanel)) return;
          if (!result || !Number.isInteger(result.scene_index) ||
              !rows[result.scene_index]) throw new Error("No valid scene revision returned.");
          preparedSceneIndex = result.status === "DRAFT_SCRIPT_REVISION"
            ? result.scene_index : null;
          originalScript.textContent = "Original narration: " + result.original_narration;
          proposedScript.value = result.proposed_narration;
          scriptMessage.textContent = result.explanation ||
            "Review this suggestion and confirm before changing the scene.";
          if (preparedSceneIndex === null) {
            feedback("No automatic rewrite was performed. Use an explicit replace instruction in the saved review notes.", true);
          }
        } catch (err) {
          feedback(err.message || "A saved narration correction review is needed.", true);
        } finally {
          busy = false;
          scriptSuggestionButton.disabled = false;
        }
      }, entry);
      reviewPanel.appendChild(scriptSuggestionButton);
      var budgetNotice = document.createElement("p");
      budgetNotice.className = "hint";
      budgetNotice.textContent = "Checking optional AI rewrite availability. Paid model requests are disabled unless the owner configures verified pricing and a daily budget.";
      reviewPanel.appendChild(budgetNotice);
      var aiRewriteButton = button("Request optional AI rewrite (may incur charges)", async function () {
        if (active() !== project || busy) return;
        if (!window.confirm("This model request may incur charges and uses one of two daily reservations. Provider charges are not yet settled or reconciled. The result is a draft only. Continue?")) return;
        busy = true;
        aiRewriteButton.disabled = true;
        try {
          var result = await bridge.api(basePath(project) + "/" +
            encodeURIComponent(entry.id) + "/assistant/previews/" +
            encodeURIComponent(latestPreview.id) + "/ai-script-revision", {
              method: "POST",
              body: JSON.stringify({confirm_billable_model_request: true})
            });
          if (active() !== project || !host.contains(reviewPanel)) return;
          if (!result || result.status !== "DRAFT_SCRIPT_REVISION" ||
              !Number.isInteger(result.scene_index) || !rows[result.scene_index]) {
            throw new Error("The model did not return a supported draft.");
          }
          preparedSceneIndex = result.scene_index;
          originalScript.textContent = "Original narration: " + result.original_narration;
          proposedScript.value = result.proposed_narration;
          scriptMessage.textContent = result.explanation +
            " Model use may have incurred charges; provider cost is not yet reconciled.";
          feedback("AI revision is a draft. Review it and use the separate Apply button if acceptable.");
        } catch (err) {
          feedback(err.message || "Optional AI rewrite unavailable; your storyboard is unchanged.", true);
        } finally {
          busy = false;
          aiRewriteButton.disabled = false;
        }
      }, entry);
      reviewPanel.appendChild(aiRewriteButton);
      aiRewriteButton.disabled = true;
      (async function loadAiBudget() {
        try {
          var budget = await bridge.api("/api/nova/creative/studio-ai-rewrite-budget", {method: "GET"});
          if (active() !== project || !host.contains(reviewPanel)) return;
          aiRewriteButton.disabled = !budget.enabled || budget.remaining_attempts <= 0;
          budgetNotice.textContent = !budget.enabled
            ? "Optional AI rewrites are disabled or pricing/budget is unconfigured. No paid model will be called."
            : "AI rewrite daily quota: " + budget.remaining_attempts + " of " +
              budget.daily_attempt_limit + " requests remaining. Budget $" +
              (budget.daily_budget_micro_usd / 1000000).toFixed(4) +
              "; reserved $" + (budget.total_reserved_micro_usd / 1000000).toFixed(4) +
              ". Charges are estimates, not settled provider billing.";
        } catch (err) {
          aiRewriteButton.disabled = true;
          budgetNotice.textContent = "AI budget status unavailable; model rewrite is blocked here.";
        }
      })();
      var applyScriptButton = button("Use proposed text in unsaved scene", function () {
        if (preparedSceneIndex === null || !rows[preparedSceneIndex]) {
          feedback("Create a supported narration suggestion first.", true);
          return;
        }
        var scene = rows[preparedSceneIndex];
        var existing = originalScript.textContent.slice("Original narration: ".length);
        if (scene.narration !== existing) {
          feedback("The scene has changed since the suggestion. Reopen its review before applying.", true);
          return;
        }
        if (!proposedScript.value.trim() || proposedScript.value.length > 6000) {
          feedback("Proposed narration must be between 1 and 6000 characters.", true);
          return;
        }
        scene.narration = proposedScript.value;
        // Previously timed captions describe the old words. Reset them for
        // a fresh caption review instead of silently keeping stale cues.
        scene.caption_cues = [];
        scene.caption_cues_raw = "";
        scene.revision_note = "Narration correction applied as draft; review captions and timing before saving.";
        renderRows();
        feedback("Narration changed only in the unsaved editor. Review captions and scene duration, then save and reapprove.");
        preparedSceneIndex = null;
      }, entry);
      reviewPanel.appendChild(applyScriptButton);
      reviewPanel.appendChild(scriptProposal);
      var reviewStatus = document.createElement("p");
      reviewStatus.setAttribute("role", "status");
      reviewStatus.textContent = previousReview.status
        ? "Previous review: " + previousReview.status.replace(/_/g, " ").toLowerCase()
        : "Not yet reviewed.";
      reviewPanel.appendChild(reviewStatus);
      var submitReview = button("Save MP4 quality review", async function () {
        if (active() !== project || !video.src) {
          reviewStatus.textContent = "Load and review the saved video before submitting this checklist.";
          return;
        }
        if (busy) return;
        busy = true;
        submitReview.disabled = true;
        try {
          var body = {
            notes: notes.value.trim(),
            correction_category: categorySelect.value,
            correction_scene_index: sceneSelect.value === "" ? null : Number(sceneSelect.value)
          };
          reviewChecks.forEach(function (field) {
            body[field[0]] = controls[field[0]].checked;
          });
          var result = await bridge.api(basePath(project) + "/" +
            encodeURIComponent(entry.id) + "/previews/" +
            encodeURIComponent(latestPreview.id) + "/review", {
              method: "PUT", body: JSON.stringify(body)
            });
          if (active() !== project || !host.contains(reviewPanel)) return;
          reviewStatus.textContent = result.status === "REVIEW_PASSED"
            ? "Preview QC passed. Publishing and commercial approval are still separate."
            : "Changes required. Save edits, reapprove and render a new preview.";
          feedback(result.message || "MP4 quality review saved.");
        } catch (err) {
          reviewStatus.textContent = err.message || "MP4 review could not be saved.";
        } finally {
          busy = false;
          submitReview.disabled = false;
        }
      }, entry);
      reviewPanel.appendChild(submitReview);
      videoPanel.appendChild(reviewPanel);
    } else {
      var noPreview = document.createElement("p");
      noPreview.className = "hint";
      noPreview.textContent = "No saved storyboard MP4 preview is available yet. Save and approve this plan, then render a preview to review real narration.";
      videoPanel.appendChild(noPreview);
    }
    rehearsal.appendChild(videoPanel);
    video.addEventListener("timeupdate", function () {
      if (Number.isFinite(video.currentTime)) {
        playhead.value = String(Math.min(Number(playhead.max), video.currentTime));
        rehearse();
      }
    });
    video.addEventListener("ended", function () { rehearse(); });
    function editableCues(scene) {
      if (scene.caption_cues_raw === undefined) return scene.caption_cues || [];
      if (!scene.caption_cues_raw.trim()) return [];
      return scene.caption_cues_raw.split(/\r?\n/).map(function (line) {
        var parts = line.split("|");
        return {
          start_seconds: Number(parts[0]), end_seconds: Number(parts[1]),
          text: parts.length === 3 ? parts[2].trim() : ""
        };
      }).filter(function (cue) {
        return Number.isFinite(cue.start_seconds) &&
          Number.isFinite(cue.end_seconds) &&
          cue.start_seconds >= 0 && cue.end_seconds > cue.start_seconds && cue.text;
      });
    }
    function rehearse() {
      var total = rows.reduce(function (sum, item) {
        return sum + Math.max(0, Number(item.duration_seconds) || 0);
      }, 0);
      playhead.max = String(total || 1);
      var position = Math.min(Number(playhead.value) || 0, Math.max(0, total - 0.001));
      var offset = 0, active = null, relative = 0, number = 0;
      rows.some(function (scene, index) {
        var length = Math.max(0, Number(scene.duration_seconds) || 0);
        if (position < offset + length) {
          active = scene; relative = position - offset; number = index + 1;
          return true;
        }
        offset += length;
        return false;
      });
      rehearsalStatus.textContent = active
        ? position.toFixed(1) + "s / " + total.toFixed(1) + "s — Scene " + number +
          ": " + active.heading + " (" + relative.toFixed(1) + "s in scene)"
        : "Add scenes to inspect planned caption timing.";
      rehearsalNarration.textContent = active ? "Narration script: " + (active.narration || "(none)") : "";
      var cue = active && editableCues(active).find(function (item) {
        return relative >= item.start_seconds && relative < item.end_seconds;
      });
      rehearsalCaption.textContent = !active ? "" : cue
        ? "Planned caption: " + cue.text
        : "No manual caption here; the renderer may use estimated timing.";
    }
    playhead.addEventListener("input", function () {
      if (video.src && Number.isFinite(video.duration) && video.duration > 0) {
        video.currentTime = Math.min(video.duration, Number(playhead.value));
      }
      rehearse();
    });
    var narrationLabel = document.createElement("label");
    narrationLabel.textContent = "Offline narrator voice (basic synthetic preview only)";
    var voicePicker = document.createElement("select");
    voicePicker.add(new Option("English — US", "en-us"));
    voicePicker.add(new Option("English — UK", "en-gb"));
    voicePicker.value = entry.narrator_voice || "en-us";
    narrationLabel.appendChild(voicePicker);
    host.appendChild(narrationLabel);
    var speedLabel = document.createElement("label");
    speedLabel.textContent = "Speaking speed (words per minute)";
    var speedPicker = document.createElement("select");
    [115, 130, 148, 165, 180].forEach(function (wpm) {
      speedPicker.add(new Option(wpm + " WPM", String(wpm)));
    });
    if (![115,130,148,165,180].includes(Number(entry.narrator_speed))) {
      speedPicker.add(new Option(String(entry.narrator_speed || 148) + " WPM", String(entry.narrator_speed || 148)));
    }
    speedPicker.value = String(entry.narrator_speed || 148);
    speedLabel.appendChild(speedPicker);
    host.appendChild(speedLabel);
    var list = document.createElement("div");
    host.appendChild(list);
    function renderRows() {
      list.replaceChildren();
      rows.forEach(function (scene, index) {
        var fieldset = document.createElement("fieldset");
        var legend = document.createElement("legend");
        legend.textContent = "Scene " + (index + 1);
        fieldset.appendChild(legend);
        function editable(labelText, value, maxLength, onChange, multiline) {
          var label = document.createElement("label");
          label.textContent = labelText;
          var field = document.createElement(multiline ? "textarea" : "input");
          field.value = value;
          field.maxLength = maxLength;
          if (multiline) field.rows = 3;
          field.addEventListener("input", function () { onChange(field.value); });
          label.appendChild(field);
          fieldset.appendChild(label);
        }
        editable("Scene heading", scene.heading, 120, function (value) { scene.heading = value; }, false);
        editable("Visual direction", scene.visual_note, 1500, function (value) { scene.visual_note = value; }, true);
        editable("Revision brief from quality review (planning only)", scene.revision_note || "", 2000, function (value) { scene.revision_note = value; }, true);
        var visualLabel = document.createElement("label");
        visualLabel.textContent = "Scene image from this project (optional)";
        var visualPicker = document.createElement("select");
        visualPicker.add(new Option("Use Studio title-card preview", ""));
        visualAssets.forEach(function (asset) {
          visualPicker.add(new Option(asset.title || asset.id, asset.id));
        });
        if (scene.visual_asset_id && !visualAssets.some(function (item) { return item.id === scene.visual_asset_id; })) {
          visualPicker.add(new Option("Previously selected image unavailable — choose another", scene.visual_asset_id));
        }
        visualPicker.value = scene.visual_asset_id || "";
        visualPicker.addEventListener("change", function () {
          scene.visual_asset_id = visualPicker.value || null;
        });
        visualLabel.appendChild(visualPicker);
        fieldset.appendChild(visualLabel);
        var transitionLabel = document.createElement("label");
        transitionLabel.textContent = "Visual transition into scene";
        var transitionPicker = document.createElement("select");
        transitionPicker.add(new Option("Direct cut", "cut"));
        transitionPicker.add(new Option("Fade in from black (0.5s max)", "fade"));
        transitionPicker.value = scene.transition;
        transitionPicker.addEventListener("change", function () {
          scene.transition = transitionPicker.value;
        });
        transitionLabel.appendChild(transitionPicker);
        fieldset.appendChild(transitionLabel);
        editable("Narration / dialogue", scene.narration, 6000, function (value) { scene.narration = value; }, true);
        var captionLabel = document.createElement("label");
        captionLabel.textContent = "Optional corrected captions: one per line as START | END | TEXT (seconds within this scene)";
        var captionText = document.createElement("textarea");
        captionText.rows = 3;
        captionText.placeholder = "0.0 | 2.5 | Welcome to my video";
        captionText.value = (scene.caption_cues || []).map(function (cue) {
          return cue.start_seconds + " | " + cue.end_seconds + " | " + cue.text;
        }).join("\n");
        captionText.addEventListener("input", function () {
          scene.caption_cues_raw = captionText.value;
          rehearse();
        });
        captionLabel.appendChild(captionText);
        fieldset.appendChild(captionLabel);
        var label = document.createElement("label");
        label.textContent = "Duration in seconds";
        var seconds = document.createElement("input");
        seconds.type = "number"; seconds.min = "1"; seconds.max = "600"; seconds.step = "1";
        seconds.value = String(scene.duration_seconds);
        seconds.addEventListener("change", function () { scene.duration_seconds = Number(seconds.value); rehearse(); });
        label.appendChild(seconds);
        fieldset.appendChild(label);
        if (entry.status === "approved" && (entry.content_mode === "faceless" || entry.content_mode === "education") &&
            scene.duration_seconds >= 2 && scene.duration_seconds <= 12) {
          fieldset.appendChild(button("Render this saved scene (free preview)", async function () {
            if (busy || active() !== project) return;
            if (!window.confirm("Render the APPROVED saved version of this scene as a review-only MP4? Unsaved edits are not included.")) return;
            busy = true;
            try {
              var result = await bridge.api(basePath(project) + "/" +
                encodeURIComponent(entry.id) + "/scenes/" + index + "/render-preview", {method: "POST"});
              if (active() !== project) return;
              if (!result || result.status !== "PREVIEW_RENDERED") throw new Error("No scene MP4 was confirmed.");
              feedback("Scene " + (index + 1) + " preview saved privately. Full video and original are unchanged.");
              if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
            } catch (err) {
              feedback(err.message || "This scene could not be rendered. Existing videos are preserved.", true);
            } finally { busy = false; }
          }, scene));
        }
        fieldset.appendChild(button("Remove scene", function () {
          rows.splice(index, 1);
          renderRows();
        }, scene));
        list.appendChild(fieldset);
      });
      rehearse();
    }
    renderRows();
    var historyPanel = document.createElement("fieldset");
    var historyTitle = document.createElement("legend");
    historyTitle.textContent = "Previously saved storyboard versions";
    historyPanel.appendChild(historyTitle);
    var historyNote = document.createElement("p");
    historyNote.className = "hint";
    historyNote.textContent = "Review and compare past saved versions. Loading a previous version only opens it as a draft; it does not overwrite the saved plan.";
    historyPanel.appendChild(historyNote);
    var historyItems = document.createElement("div");
    historyPanel.appendChild(historyItems);
    host.appendChild(historyPanel);
    (async function loadHistory() {
      try {
        var history = await bridge.api(basePath(project) + "/" +
          encodeURIComponent(entry.id) + "/storyboard-revisions", {method: "GET"});
        if (active() !== project || !host.contains(historyPanel)) return;
        historyItems.replaceChildren();
        (history.revisions || []).forEach(function (version) {
          var item = document.createElement("p");
          var label = document.createElement("span");
          label.textContent = (version.saved_at || "Saved version") + " — " +
            ((version.scenes || []).length) + " scenes ";
          item.appendChild(label);
          item.appendChild(button("Open as unsaved draft", function () {
            if (!window.confirm("Open this earlier storyboard in the editor? Unsaved edits in the current editor will be replaced; the saved video plan is not changed until Save storyboard.")) return;
            rows = (version.scenes || []).map(function (scene) {
              return {
                heading: scene.heading || "", visual_note: scene.visual_note || "",
                revision_note: scene.revision_note || "", narration: scene.narration || "",
                duration_seconds: Number(scene.duration_seconds) || 1,
                visual_asset_id: scene.visual_asset_id || null,
                transition: scene.transition === "fade" ? "fade" : "cut",
                caption_cues: (scene.caption_cues || []).slice()
              };
            });
            voicePicker.value = version.narrator_voice || "en-us";
            speedPicker.value = String(version.narrator_speed || 148);
            renderRows();
            feedback("Previous version opened as unsaved draft. Review before saving.");
          }, version));
          historyItems.appendChild(item);
        });
        if (!historyItems.children.length) historyItems.textContent = "No previous saved versions.";
      } catch (err) {
        historyItems.textContent = "Storyboard history is unavailable.";
      }
    })();
    host.appendChild(button("Add scene", function () {
      if (rows.length >= 60) { feedback("Storyboard supports up to 60 scenes.", true); return; }
      rows.push({ heading: "New scene", visual_note: "", narration: "", duration_seconds: 60, visual_asset_id: null, transition: "cut", caption_cues: [] });
      renderRows();
    }, entry));
    host.appendChild(button("Save storyboard", async function () {
      if (busy || active() !== project) return;
      var valid = rows.length > 0 && rows.length <= 60 && rows.every(function (scene) {
        return scene.heading.trim() && Number.isInteger(scene.duration_seconds) &&
          scene.duration_seconds >= 1 && scene.duration_seconds <= 600;
      });
      var seconds = rows.reduce(function (sum, scene) { return sum + scene.duration_seconds; }, 0);
      if (!valid || seconds !== entry.duration_seconds) {
        feedback("Each scene needs a heading and valid duration; scene durations must total " +
          entry.duration_seconds + " seconds. Current total: " + seconds + ".", true);
        return;
      }
      try {
        rows.forEach(function (scene, i) {
          if (scene.caption_cues_raw === undefined) return;
          var raw = scene.caption_cues_raw.trim();
          var previous = 0;
          var cues = raw ? raw.split(/\r?\n/).map(function (line) {
            var parts = line.split("|");
            if (parts.length !== 3) throw new Error("Scene " + (i + 1) + ": caption format must be START | END | TEXT.");
            var start = Number(parts[0].trim());
            var end = Number(parts[1].trim());
            var text = parts[2].trim();
            if (!Number.isFinite(start) || !Number.isFinite(end) || !text ||
                start < previous || end <= start || end > scene.duration_seconds) {
              throw new Error("Scene " + (i + 1) + ": captions must be ordered, nonoverlapping, and fit within scene time.");
            }
            previous = end;
            return { start_seconds: start, end_seconds: end, text: text };
          }) : [];
          if (cues.length > 30) throw new Error("Scene " + (i + 1) + ": maximum 30 captions.");
          scene.caption_cues = cues;
        });
      } catch (err) {
        feedback(err.message || "Fix the caption timing before saving.", true);
        return;
      }
      busy = true;
      try {
        var saved = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) +
          "/storyboard", { method: "PUT", body: JSON.stringify({ scenes: rows, narrator_voice: voicePicker.value, narrator_speed: Number(speedPicker.value) }) });
        if (active() !== project) return;
        feedback(saved.status === "ready_for_review"
          ? "Storyboard saved. Review and reapprove the edited plan before production."
          : "Storyboard saved in this video plan; no media has been generated.");
        host.replaceChildren();
        await load();
      } catch (err) {
        feedback(err.message || "Storyboard could not be saved.", true);
      } finally { busy = false; }
    }, entry));
    host.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function editChapters(entry, proposedChapters) {
    var project = requestProject();
    if (!project || (busy && !Array.isArray(proposedChapters))) return;
    var host = $("calendar-chapters");
    host.replaceChildren();
    try {
      var detail = await bridge.api("/api/nova/creative/projects/" + encodeURIComponent(project), { method: "GET" });
      if (active() !== project) return;
      var videos = (detail.assets || []).filter(function (a) {
        return a.kind === "video" && a.url && a.media_available !== false && a.id;
      });
      var chapterRows = (Array.isArray(proposedChapters) ? proposedChapters : (entry.chapters || [])).map(function (chapter) {
        return {
          title: chapter.title,
          duration_seconds: chapter.duration_seconds,
          revision_note: chapter.revision_note || "",
          asset_ids: (chapter.asset_ids || []).slice()
        };
      });
      var title = document.createElement("h3");
      title.textContent = "Video chapters: " + entry.topic;
      host.appendChild(title);
      var note = document.createElement("p");
      note.className = "hint";
      note.textContent = (Array.isArray(proposedChapters)
        ? "Nova prepared an editable chapter suggestion. It has NOT been saved. Review every title and duration, then choose Save chapter plan to apply."
        : "Build the full video one chapter at a time. Each chapter is 2–10 minutes and uses previously saved clips. Chapter durations must add up to the entire planned length. Saving edits requires another approval.");
      host.appendChild(note);
      var readinessPanel = document.createElement("fieldset");
      var readinessTitle = document.createElement("legend");
      readinessTitle.textContent = "Rebuild affected chapters";
      readinessPanel.appendChild(readinessTitle);
      var readinessLegendHelp = document.createElement("p");
      readinessLegendHelp.className = "hint";
      readinessLegendHelp.textContent = "Final-master export requires each saved chapter MP4 to be verified and its exact file to pass visuals, audio, captions and continuity review. This does not authorize publishing.";
      readinessPanel.appendChild(readinessLegendHelp);
      var readinessList = document.createElement("div");
      readinessPanel.appendChild(readinessList);
      var readinessButton = button("Check chapter rebuild readiness", async function () {
        if (active() !== project || busy) return;
        readinessButton.disabled = true;
        readinessList.textContent = "Checking saved chapter media and current clip order...";
        try {
          var plan = await bridge.api(basePath(project) + "/" +
            encodeURIComponent(entry.id) + "/chapter-rebuild-plan", {method: "GET"});
          if (active() !== project || !host.contains(readinessPanel)) return;
          readinessList.replaceChildren();
          (plan.chapters || []).forEach(function (chapter) {
            var line = document.createElement("p");
            var stateLabel = chapter.status !== "REUSABLE"
              ? "rebuild needed"
              : chapter.review_status === "REVIEW_PASSED"
                ? "MP4 verified; quality review passed"
                : chapter.review_status === "CHANGES_REQUIRED"
                  ? "MP4 verified; corrections required"
                  : "MP4 verified; quality review required";
            line.textContent = "Chapter " + (chapter.chapter_index + 1) + " — " + chapter.title +
              ": " + stateLabel;
            if (chapter.status === "NEEDS_REBUILD" && plan.plan_status === "approved") {
              line.appendChild(button("Rebuild this chapter", async function () {
                if (busy || active() !== project) return;
                if (!window.confirm("Rebuild only chapter " + (chapter.chapter_index + 1) +
                    " from approved saved clips? Earlier videos remain saved.")) return;
                busy = true;
                try {
                  var result = await bridge.api(basePath(project) + "/" +
                    encodeURIComponent(entry.id) + "/chapters/" + chapter.chapter_index +
                    "/rebuild", {method: "POST"});
                  if (active() !== project) return;
                  if (result.status !== "ASSEMBLED_REVIEW_REQUIRED") {
                    throw new Error("Chapter rebuild was not verified.");
                  }
                  feedback("Chapter " + (chapter.chapter_index + 1) +
                    " saved for review. Recheck readiness before exporting the full master.");
                  if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
                } catch (err) {
                  feedback(err.message || "Chapter rebuild failed; existing videos remain saved.", true);
                } finally {
                  busy = false;
                  if (active() === project && host.contains(readinessPanel)) readinessButton.click();
                }
              }, chapter));
            }
            if (chapter.status === "REUSABLE" && chapter.asset_id) {
              var review = chapter.quality_review || {};
              var qc = document.createElement("fieldset");
              var qcTitle = document.createElement("legend");
              qcTitle.textContent = "Review Chapter " + (chapter.chapter_index + 1) + " MP4";
              qc.appendChild(qcTitle);
              var qcStatus = document.createElement("p");
              qcStatus.setAttribute("role", "status");
              qcStatus.textContent = chapter.review_status === "REVIEW_PASSED"
                ? "This exact chapter MP4 passed quality review."
                : chapter.review_status === "CHANGES_REQUIRED"
                  ? "Corrections required for this chapter MP4. Add replacement footage, rebuild, and review the new version."
                  : "No valid passed quality review for this exact chapter MP4.";
              qc.appendChild(qcStatus);
              var chapterVideo = document.createElement("video");
              chapterVideo.controls = true;
              chapterVideo.preload = "metadata";
              chapterVideo.playsInline = true;
              chapterVideo.style.maxWidth = "100%";
              chapterVideo.style.maxHeight = "340px";
              chapterVideo.setAttribute("aria-label", "Saved verified chapter video");
              var safeForPlayback = Number.isFinite(Number(chapter.file_size_bytes)) &&
                Number(chapter.file_size_bytes) > 0 &&
                Number(chapter.file_size_bytes) <= 128 * 1024 * 1024;
              if (safeForPlayback && typeof bridge.fetchProtectedVideo === "function") {
                qc.appendChild(button("Load this chapter MP4", async function () {
                  if (active() !== project) return;
                  try {
                    var blob = await bridge.fetchProtectedVideo(project, chapter.asset_id);
                    if (active() !== project || !readinessList.contains(qc)) return;
                    if (chapterVideo.dataset.objectUrl) URL.revokeObjectURL(chapterVideo.dataset.objectUrl);
                    var objectUrl = URL.createObjectURL(blob);
                    chapterVideo.dataset.objectUrl = objectUrl;
                    chapterVideo.src = objectUrl;
                    if (!qc.contains(chapterVideo)) qc.appendChild(chapterVideo);
                    feedback("Chapter MP4 loaded. Review narration, captions, visuals and chapter ending.");
                  } catch (err) {
                    feedback(err.message || "Protected chapter playback unavailable.", true);
                  }
                }, chapter));
              } else {
                var playbackHint = document.createElement("p");
                playbackHint.className = "hint";
                playbackHint.textContent = "This chapter is too large (or size is unknown) for safe in-memory playback. Review it through the protected Studio asset download before saving quality notes.";
                qc.appendChild(playbackHint);
              }
              var qcChecks = [
                ["visuals_ok", "Visuals and scene transitions reviewed"],
                ["audio_ok", "Narration and audio reviewed"],
                ["captions_ok", "Captions reviewed"],
                ["continuity_ok", "Chapter starts and ends correctly"]
              ];
              var qcInputs = {};
              qcChecks.forEach(function (field) {
                var label = document.createElement("label");
                var cb = document.createElement("input");
                cb.type = "checkbox";
                cb.checked = Boolean(review[field[0]]);
                qcInputs[field[0]] = cb;
                label.appendChild(cb);
                label.appendChild(document.createTextNode(" " + field[1]));
                qc.appendChild(label);
              });
              var qcNotes = document.createElement("textarea");
              qcNotes.rows = 2;
              qcNotes.maxLength = 2000;
              qcNotes.placeholder = "Chapter correction notes";
              qcNotes.value = review.notes || "";
              qcNotes.setAttribute("aria-label", "Chapter quality review notes");
              qc.appendChild(qcNotes);
              qc.appendChild(button("Save chapter quality review", async function () {
                if (busy || active() !== project) return;
                var body = {notes: qcNotes.value};
                qcChecks.forEach(function (field) { body[field[0]] = qcInputs[field[0]].checked; });
                var passedAll = qcChecks.every(function (field) { return body[field[0]] === true; });
                if (!passedAll && !body.notes.trim()) {
                  feedback("Enter specific correction notes when a chapter fails quality review.", true);
                  qcNotes.focus();
                  return;
                }
                busy = true;
                var didSaveReview = false;
                try {
                  var saved = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) +
                    "/chapters/" + chapter.chapter_index + "/review/" +
                    encodeURIComponent(chapter.asset_id), {method: "PUT", body: JSON.stringify(body)});
                  if (active() !== project || !readinessList.contains(qc)) return;
                  qcStatus.textContent = "Saved review: " + saved.status.replace(/_/g, " ").toLowerCase() +
                    ". Refresh readiness before final-master export. This does not approve publishing.";
                  didSaveReview = true;
                  feedback(saved.message || "Chapter review saved. Updating master readiness.");
                } catch (err) {
                  feedback(err.message || "Chapter review was not saved.", true);
                } finally {
                  busy = false;
                  if (didSaveReview && active() === project && host.contains(readinessPanel)) {
                    readinessButton.click();
                  }
                }
              }, chapter));
              line.appendChild(qc);
            }
            readinessList.appendChild(line);
          });
          var summary = document.createElement("p");
          var rebuildCount = (plan.needs_rebuild_indices || []).length;
          var reviewCount = (plan.needs_review_indices || []).length;
          var correctionCount = (plan.needs_correction_indices || []).length;
          summary.textContent = plan.master_ready
            ? "Ready to update final master for private review: all " +
              plan.reusable_chapters + " chapter MP4s are verified and their exact versions passed quality review."
            : plan.plan_status !== "approved"
              ? "Save and approve the chapter plan before rebuilding or exporting."
              : rebuildCount
                ? rebuildCount + " chapter(s) need rebuilding. " +
                  reviewCount + " additional chapter(s) need quality review; " +
                  correctionCount + " have corrections requested."
                : reviewCount
                  ? reviewCount + " chapter(s) need quality review before final-master export (" +
                    correctionCount + " with corrections requested). Review each chapter MP4 below, " +
                    "correct failures, and check readiness again."
                  : "Final master is not ready. Check chapter approvals and saved media.";
          readinessList.appendChild(summary);
          if (plan.master_ready && plan.version_sha256 && plan.plan_status === "approved") {
            var updateButton = button("Update Final Master (review-only)", async function () {
              if (busy || active() !== project) return;
              var matching = plan.chapters.every(function (ch, i) {
                return ch.status === "REUSABLE" && ch.review_status === "REVIEW_PASSED" &&
                  ch.chapter_index === i && Boolean(ch.asset_id);
              });
              if (!matching) {
                feedback("Some chapters must be rebuilt before final master export.", true);
                return;
              }
              if (!window.confirm("Create a NEW review-only final master from all " +
                  plan.reusable_chapters + " verified saved chapters? Older masters will remain available. No paid AI generation or publishing.")) return;
              busy = true;
              updateButton.disabled = true;
              try {
                var result = await bridge.api(basePath(project) + "/" +
                  encodeURIComponent(entry.id) + "/update-final-master", {
                    method: "POST",
                    body: JSON.stringify({
                      version_sha256: plan.version_sha256,
                      confirm_rebuild: true
                    })
                  });
                if (active() !== project) return;
                if (!result || (result.status !== "QUEUED" && result.status !== "ALREADY_RUNNING")) {
                  throw new Error(result && result.message || "No master export job was confirmed.");
                }
                feedback(result.status === "QUEUED"
                  ? "Updated master queued. Use Master job status to follow progress. Older masters remain saved."
                  : "A master export is already running. Check its saved status before starting another.");
              } catch (err) {
                feedback(err.message || "Updated master export was not started. Previous videos are preserved.", true);
              } finally {
                busy = false;
                updateButton.disabled = false;
              }
            }, entry);
            readinessList.appendChild(updateButton);
          }
        } catch (err) {
          readinessList.textContent = "Could not check chapter readiness: " + (err.message || "unknown error");
        } finally {
          readinessButton.disabled = false;
        }
      }, entry);
      readinessPanel.appendChild(readinessButton);
      host.appendChild(readinessPanel);
      var list = document.createElement("div");
      host.appendChild(list);
      function displayRows() {
        list.replaceChildren();
        chapterRows.forEach(function (row, index) {
          var panel = document.createElement("fieldset");
          panel.dataset.chapterIndex = String(index);
          var legend = document.createElement("legend");
          legend.textContent = "Chapter " + (index + 1);
          panel.appendChild(legend);
          var input = document.createElement("input");
          input.value = row.title;
          input.maxLength = 200;
          input.placeholder = "Chapter title";
          input.setAttribute("aria-label", "Chapter title");
          input.addEventListener("input", function () { row.title = input.value; });
          panel.appendChild(input);
          var revisionLabel = document.createElement("label");
          revisionLabel.textContent = "Chapter correction brief (edit before saving)";
          var revisionInput = document.createElement("textarea");
          revisionInput.rows = 3;
          revisionInput.maxLength = 2000;
          revisionInput.value = row.revision_note || "";
          revisionInput.addEventListener("input", function () {
            row.revision_note = revisionInput.value;
          });
          revisionLabel.appendChild(revisionInput);
          panel.appendChild(revisionLabel);
          var mins = document.createElement("input");
          mins.type = "number";
          mins.min = "2";
          mins.max = "10";
          mins.step = "1";
          mins.value = String(row.duration_seconds / 60);
          mins.setAttribute("aria-label", "Chapter minutes");
          mins.addEventListener("change", function () { row.duration_seconds = Math.round(Number(mins.value) * 60); });
          panel.appendChild(mins);
          var selector = document.createElement("div");
          videos.forEach(function (asset) {
            var label = document.createElement("label");
            var check = document.createElement("input");
            check.type = "checkbox";
            check.checked = row.asset_ids.includes(asset.id);
            check.addEventListener("change", function () {
              if (check.checked && !row.asset_ids.includes(asset.id)) row.asset_ids.push(asset.id);
              else if (!check.checked) row.asset_ids = row.asset_ids.filter(function (id) { return id !== asset.id; });
            });
            label.appendChild(check);
            label.appendChild(document.createTextNode(" " + (asset.title || asset.id)));
            selector.appendChild(label);
          });
          panel.appendChild(selector);
          if (row.asset_ids.length) {
            var replacePanel = document.createElement("fieldset");
            var replaceLegend = document.createElement("legend");
            replaceLegend.textContent = "Replace a clip using a saved revised storyboard video";
            replacePanel.appendChild(replaceLegend);
            var replacementHelp = document.createElement("p");
            replacementHelp.className = "hint";
            replacementHelp.textContent = "This action replaces one clip reference only. Existing MP4s are preserved; save your other edits separately before replacing a clip.";
            replacePanel.appendChild(replacementHelp);
            var oldPicker = document.createElement("select");
            row.asset_ids.forEach(function (id) {
              var asset = videos.find(function (item) { return item.id === id; });
              oldPicker.add(new Option(asset ? (asset.title || asset.id) : id, id));
            });
            oldPicker.setAttribute("aria-label", "Current clip to replace");
            replacePanel.appendChild(oldPicker);
            var newPicker = document.createElement("select");
            newPicker.add(new Option("Find saved replacement videos first", ""));
            newPicker.disabled = true;
            newPicker.setAttribute("aria-label", "Revised completed storyboard MP4");
            replacePanel.appendChild(newPicker);
            var replacementState = document.createElement("p");
            replacementState.className = "hint";
            replacementState.setAttribute("role", "status");
            replacePanel.appendChild(replacementState);
            var replaceButton = button("Replace clip and require review", async function () {
              if (busy || active() !== project || !newPicker.value) return;
              if (!window.confirm("Replace only this saved chapter clip? The plan will need reapproval, and previous MP4s remain stored.")) return;
              busy = true;
              try {
                var result = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) +
                  "/chapters/" + index + "/replace-clip", {
                    method: "POST",
                    body: JSON.stringify({
                      old_asset_id: oldPicker.value,
                      new_asset_id: newPicker.value
                    })
                  });
                if (active() !== project) return;
                if (!result || result.status !== "REPLACEMENT_SAVED_REVIEW_REQUIRED") {
                  throw new Error("The clip replacement was not confirmed.");
                }
                feedback("Chapter " + (index + 1) +
                  " clip replacement saved. Reapprove the plan, rebuild the chapter, then update the master. Earlier videos remain stored.");
                host.replaceChildren();
                await load();
              } catch (err) {
                feedback(err.message || "Clip replacement failed; original video preserved.", true);
              } finally { busy = false; }
            }, row);
            replaceButton.disabled = true;
            replacePanel.appendChild(replaceButton);
            replacePanel.appendChild(button("Find saved replacement MP4s", async function () {
              if (busy || active() !== project) return;
              replacementState.textContent = "Checking saved replacement candidates...";
              try {
                var data = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) +
                  "/chapters/" + index + "/replacement-options", {method: "GET"});
                if (active() !== project || !replacePanel.isConnected) return;
                newPicker.replaceChildren(new Option("Choose a different saved video", ""));
                (data.replacement_candidates || []).forEach(function (asset) {
                  if (!row.asset_ids.includes(asset.asset_id)) {
                    newPicker.add(new Option((asset.title || asset.asset_id) +
                      (asset.duration_seconds ? " — " + Math.round(asset.duration_seconds) + " sec" : ""), asset.asset_id));
                  }
                });
                newPicker.disabled = newPicker.options.length <= 1;
                replaceButton.disabled = true;
                replacementState.textContent = newPicker.disabled
                  ? "No saved revised MP4 is currently eligible. Produce and save a new storyboard preview first."
                  : "Select the original clip and a saved replacement. The server rechecks access and file integrity before saving.";
              } catch (err) {
                replacementState.textContent = err.message || "Could not find replacement videos.";
              }
            }, row));
            newPicker.addEventListener("change", function () {
              replaceButton.disabled = !newPicker.value || newPicker.value === oldPicker.value;
            });
            oldPicker.addEventListener("change", function () {
              replaceButton.disabled = !newPicker.value || newPicker.value === oldPicker.value;
            });
            panel.appendChild(replacePanel);
          }
          panel.appendChild(button("Remove chapter", function () {
            chapterRows.splice(index, 1);
            displayRows();
          }, row));
          if (entry.status === "approved" && row.asset_ids.length >= 2) {
            panel.appendChild(button("Assemble this chapter", async function () {
              if (busy || active() !== project) return;
              busy = true;
              feedback("Combining approved chapter " + (index + 1) + " into one MP4...");
              try {
                var out = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) +
                  "/chapters/" + index + "/assemble", { method: "POST" });
                if (active() !== project) return;
                if (out.status !== "ASSEMBLED_REVIEW_REQUIRED") throw new Error("Chapter render was not confirmed.");
                feedback("Chapter MP4 saved. Review and download it from the Studio Asset list.");
                if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
              } catch (err) {
                feedback(err.message || "Chapter render failed; source clips are unchanged.", true);
              } finally { busy = false; }
            }, row));
          }
          list.appendChild(panel);
        });
      }
      displayRows();
      host.appendChild(button("Add chapter", function () {
        if (chapterRows.length >= 24) { feedback("Maximum 24 chapters.", true); return; }
        chapterRows.push({ title: "New chapter", duration_seconds: 300, asset_ids: [] });
        displayRows();
      }, entry));
      host.appendChild(button("Save chapter plan", async function () {
        if (busy || active() !== project) return;
        if (!chapterRows.length || chapterRows.some(function (ch) {
          return !ch.title.trim() || ch.duration_seconds < 120 || ch.duration_seconds > 600;
        })) {
          feedback("Each chapter needs a title and a length of 2–10 minutes.", true);
          return;
        }
        var sum = chapterRows.reduce(function (total, ch) { return total + ch.duration_seconds; }, 0);
        if (sum !== entry.duration_seconds) {
          feedback("Chapter durations total " + Math.round(sum / 60) +
            " minutes but the plan is " + Math.round(entry.duration_seconds / 60) + " minutes.", true);
          return;
        }
        busy = true;
        try {
          var saved = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) + "/chapters", {
            method: "PUT", body: JSON.stringify({ chapters: chapterRows })
          });
          if (active() !== project) return;
          feedback(saved.status === "ready_for_review"
            ? "Chapters saved. Reapprove the plan before assembling."
            : "Chapters saved. Continue working any time.");
          host.replaceChildren();
          await load();
        } catch (err) {
          feedback(err.message || "Could not save chapters.", true);
        } finally { busy = false; }
      }, entry));
      host.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      feedback(err.message || "Unable to load chapter editor.", true);
    }
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
      var selectedById = new Map(videos.map(function (asset) { return [asset.id, asset]; }));
      var ordered = (entry.timeline_asset_ids || []).map(function (id) {
        return selectedById.get(id);
      }).filter(Boolean);
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
      showOrder();
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
      host.appendChild(button("Save timeline", async function () {
        if (busy || active() !== project) return;
        busy = true;
        feedback("Saving your ordered video timeline...");
        try {
          var saved = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) + "/timeline", {
            method: "PUT",
            body: JSON.stringify({ asset_ids: ordered.map(function (asset) { return asset.id; }) })
          });
          if (active() !== project) return;
          entry.timeline_asset_ids = saved.timeline_asset_ids || [];
          entry.status = saved.status;
          feedback(saved.status === "ready_for_review"
            ? "Timeline saved. Changes require approval again before assembly."
            : "Timeline saved. You can return to this project and resume.");
          await load();
        } catch (err) {
          feedback(err.message || "Could not save timeline.", true);
        } finally { busy = false; }
      }, entry));
      host.appendChild(button("Start MP4 assembly job", async function () {
        if (ordered.length < 2 || busy) {
          feedback("Choose at least two clips first.", true);
          return;
        }
        if (active() !== project) return;
        busy = true;
        feedback("Submitting the saved clips for background assembly. No paid provider is used.");
        try {
          var result = await bridge.api(basePath(project) + "/" + encodeURIComponent(entry.id) + "/assemble-job", {
            method: "POST",
            body: JSON.stringify({ asset_ids: ordered.map(function (item) { return item.id; }) })
          });
          if (active() !== project) return;
          var job = result.job;
          if (!job || !job.id || (result.status !== "QUEUED" && result.status !== "ALREADY_RUNNING")) {
            throw new Error(result.message || "No saved assembly job was returned.");
          }
          feedback("Assembly queued. Checking saved job progress...");
          // Poll a saved job only. Refreshing status never creates another assembly.
          for (var attempt = 0; attempt < 90 && active() === project; attempt++) {
            await new Promise(function (resolve) { setTimeout(resolve, 3000); });
            var snapshot = await bridge.api(basePath(project) + "/" +
              encodeURIComponent(entry.id) + "/assembly-status", { method: "GET" });
            var state = snapshot.status;
            if (state === "GENERATED") {
              feedback("Combined MP4 saved. Review and download from Studio's Asset list.");
              host.replaceChildren();
              if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
              return;
            }
            if (state === "INTERRUPTED_UNCONFIRMED") {
              feedback(snapshot.message || "Worker status is unconfirmed. Check saved output before retrying.", true);
              return;
            }
            if (state === "ERROR") throw new Error((snapshot.job || {}).message || "Assembly failed.");
            feedback("Video assembly: " + (state || "pending") + ". Your source clips remain saved.");
          }
          feedback("Assembly is still processing or its status could not be confirmed. Reopen the Studio project to check saved jobs.");
        } catch (err) {
          feedback(err.message || "Assembly could not be confirmed; source clips are preserved.", true);
        } finally { busy = false; }
      }, entry));
      host.scrollIntoView({ behavior: "smooth", block: "start" });
      feedback("Choose clips in the correct order and build the combined video.");
    } catch (err) {
      feedback(err.message || "Unable to load saved videos.", true);
    }
  }

  async function assembleStoryboardScenes(entry) {
    var project = requestProject();
    if (!project || busy) return;
    if (!window.confirm("Assemble only the currently approved, previously rendered scene segments? Missing scenes must be rendered individually first. Saved originals will remain unchanged.")) return;
    busy = true;
    feedback("Verifying saved scene segments and joining the review-only MP4...");
    try {
      var result = await bridge.api(basePath(project) + "/" +
        encodeURIComponent(entry.id) + "/assemble-scene-previews", {method: "POST"});
      if (active() !== project) return;
      if (!result || result.status !== "PREVIEW_RENDERED") {
        throw new Error("Studio did not confirm a verified assembled MP4.");
      }
      feedback("Assembled " + result.reused_scene_segments +
        " verified saved scenes into a private review-only MP4. No paid generation or publishing.");
      if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
    } catch (err) {
      feedback(err.message || "Assembly was not completed. Check each scene was separately rendered after your latest storyboard approval.", true);
    } finally { busy = false; }
  }
  async function renderStoryboardPreview(entry) {
    var project = requestProject();
    if (!project || busy) return;
    var selectedRevision = revision;
    busy = true;
    feedback("Rendering your approved storyboard as a local narrated preview. No paid providers or publishing.");
    try {
      var result = await bridge.api(basePath(project) + "/" +
        encodeURIComponent(entry.id) + "/render-storyboard-preview", {
          method: "POST"
        });
      if (active() !== project || selectedRevision !== revision) return;
      if (!result || result.status !== "PREVIEW_RENDERED" || !result.download_url) {
        throw new Error("Studio did not confirm a saved storyboard preview MP4.");
      }
      feedback("Storyboard preview saved in the Studio Asset list. This is an AMICOR title-card preview, not finished AI-generated footage.");
      if (typeof bridge.refreshProductionAssets === "function") await bridge.refreshProductionAssets();
    } catch (err) {
      feedback(err.message || "Storyboard preview could not be rendered; your saved scenes remain unchanged.", true);
    } finally {
      busy = false;
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
  $("studio-assistant-propose-chapters").addEventListener("click", async function () {
    var project = requestProject();
    var entryId = $("studio-assistant-entry").value;
    if (!project || busy) return;
    var plan = entries.find(function (item) { return item.id === entryId; });
    if (!plan) {
      $("studio-assistant-feedback").textContent = "Select a saved video plan first.";
      return;
    }
    if (plan.status === "canceled") {
      $("studio-assistant-feedback").textContent = "Canceled plans cannot be edited.";
      return;
    }
    if ((plan.chapters || []).length &&
        !window.confirm("This will open a suggested chapter outline in the editor. Your existing chapters will not change unless you explicitly save the new outline. Continue?")) {
      return;
    }
    busy = true;
    $("studio-assistant-propose-chapters").disabled = true;
    var selectedProject = project;
    $("studio-assistant-feedback").textContent = "Nova is preparing an editable chapter structure...";
    try {
      var result = await bridge.api(basePath(project) + "/" +
        encodeURIComponent(entryId) + "/assistant/chapter-proposal", { method: "POST" });
      if (active() !== selectedProject || $("studio-assistant-entry").value !== entryId) return;
      if (!result || result.status !== "DRAFT_SUGGESTION" ||
          !Array.isArray(result.chapters) || !result.chapters.length) {
        throw new Error("No supported chapter outline was returned.");
      }
      var proposedTotal = result.chapters.reduce(function (sum, ch) {
        return sum + Number(ch.duration_seconds);
      }, 0);
      if (proposedTotal !== plan.duration_seconds) {
        throw new Error("Suggested chapter durations do not match the saved plan.");
      }
      $("studio-assistant-feedback").textContent =
        "Suggested " + result.chapters.length +
        " editable chapters. Review and use Save chapter plan if you agree. Nothing has been saved yet.";
      await editChapters(plan, result.chapters);
    } catch (err) {
      $("studio-assistant-feedback").textContent =
        err.message || "Chapter proposal could not be prepared.";
    } finally {
      busy = false;
      $("studio-assistant-propose-chapters").disabled = false;
    }
  });
  $("studio-assistant-propose-storyboard").addEventListener("click", async function () {
    var project = requestProject();
    var entryId = $("studio-assistant-entry").value;
    var plan = entries.find(function (item) { return item.id === entryId; });
    if (!project || busy) return;
    if (!plan) {
      $("studio-assistant-feedback").textContent = "Select a saved video plan first.";
      return;
    }
    if ((plan.storyboard || []).length &&
        !window.confirm("Open a new storyboard suggestion? Existing scenes will remain saved unless you explicitly save the replacement.")) return;
    busy = true;
    $("studio-assistant-propose-storyboard").disabled = true;
    try {
      var result = await bridge.api(basePath(project) + "/" +
        encodeURIComponent(entryId) + "/assistant/storyboard-proposal", { method: "POST" });
      if (active() !== project || $("studio-assistant-entry").value !== entryId) return;
      if (!result || result.status !== "DRAFT_SUGGESTION" || !Array.isArray(result.scenes)) {
        throw new Error("No editable storyboard was returned.");
      }
      $("studio-assistant-feedback").textContent =
        "Storyboard suggestion ready. Review scenes and click Save storyboard to keep your changes.";
      await editStoryboard(plan, result.scenes);
    } catch (err) {
      $("studio-assistant-feedback").textContent = err.message || "Storyboard suggestion failed.";
    } finally {
      busy = false;
      $("studio-assistant-propose-storyboard").disabled = false;
    }
  });
  $("studio-assistant-entry").addEventListener("change", function () {
    studioAssistantHistory = [];
    $("studio-assistant-conversation").textContent = "";
    $("studio-assistant-feedback").textContent = "";
  });
  $("studio-assistant-send").addEventListener("click", async function () {
    var project = requestProject();
    var entryId = $("studio-assistant-entry").value;
    var question = $("studio-assistant-question").value.trim();
    if (!project || busy) return;
    if (!entryId || !entries.some(function (item) { return item.id === entryId; })) {
      $("studio-assistant-feedback").textContent = "Select a saved video plan first.";
      return;
    }
    if (!question) {
      $("studio-assistant-feedback").textContent = "Write a question for Nova Studio.";
      return;
    }
    busy = true;
    $("studio-assistant-send").disabled = true;
    var selectedProject = project;
    var selectedEntry = entryId;
    $("studio-assistant-feedback").textContent = "Nova is reviewing your saved plan...";
    try {
      var response = await bridge.api(basePath(project) + "/" +
        encodeURIComponent(entryId) + "/assistant", {
          method: "POST", body: JSON.stringify({
            message: question, history: studioAssistantHistory.slice(-8)
          })
        });
      if (active() !== selectedProject || $("studio-assistant-entry").value !== selectedEntry) return;
      if (!response || !response.reply) throw new Error("No assistant response returned.");
      studioAssistantHistory.push({ role: "user", content: question });
      studioAssistantHistory.push({ role: "assistant", content: response.reply });
      studioAssistantHistory = studioAssistantHistory.slice(-8);
      var conversation = $("studio-assistant-conversation");
      conversation.textContent += (conversation.textContent ? "\n\n" : "") +
        "You: " + question + "\nNova: " + response.reply;
      $("studio-assistant-question").value = "";
      $("studio-assistant-feedback").textContent = response.mode === "conversational"
        ? "AI guidance only. No changes saved or published."
        : "Basic guided mode; AI model is disabled. No provider was charged.";
    } catch (err) {
      $("studio-assistant-feedback").textContent = err.message || "Nova could not answer.";
    } finally {
      busy = false;
      $("studio-assistant-send").disabled = false;
    }
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
