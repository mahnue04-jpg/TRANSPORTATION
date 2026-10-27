(function () {
  var tokenKey = "amicor_nova_creative_token";
  var activeProjectKey = "amicor_nova_creative_active_project";
  var activeProjectId = localStorage.getItem(activeProjectKey) || null;
  var activeBrandId = null;
  var projectRowsCache = [];
  var activeProjectRevision = 0;
  var presenterScriptProjectId = null;
  var presenterSavedScriptValue = null;

  function setActiveProjectId(value) {
    var next = value || null;
    if (activeProjectId !== next) {
      activeProjectRevision += 1;
      presenterScriptProjectId = null;
      presenterSavedScriptValue = null;
      ["presenter-script", "genova-narration-script", "genova-image-file", "genova-narration-file"].forEach(function (id) {
        if ($(id)) $(id).value = "";
      });
      if ($("presenter-script")) $("presenter-script").disabled = true;
      ["genova-image-choices", "genova-narration-choices"].forEach(function (id) {
        if ($(id)) $(id).textContent = "Load the saved choices for this project to review them.";
      });
      if ($("asset-list")) $("asset-list").textContent = "Loading the selected project's assets...";
      renderProductionReadiness(null);
      if ($("genova-avatar-readiness-result")) $("genova-avatar-readiness-result").textContent = "Run the free readiness check for the selected project.";
      if ($("check-genova-avatar-readiness")) $("check-genova-avatar-readiness").disabled = false;
      ["save-presenter-script", "generate-presenter-voice", "preview-talking-presenter"].forEach(function (id) {
        if ($(id)) $(id).disabled = true;
      });
      renderPreflight(null);
    }
    activeProjectId = next;
    if (activeProjectId) localStorage.setItem(activeProjectKey, activeProjectId);
    else localStorage.removeItem(activeProjectKey);
    updateActiveProjectLabel();
  }

  function updateActiveProjectLabel() {
    var el = $("active-project-label");
    if (!el) return;
    if (!activeProjectId) {
      el.textContent = "No project selected yet. Click Select Second Commercial, or Build will pick it for you.";
      return;
    }
    var row = (typeof projectRowsCache !== "undefined" ? projectRowsCache : []).find(function (item) {
      return item.id === activeProjectId;
    });
    el.textContent = row
      ? ("Active project: " + row.title + " · " + activeProjectId)
      : ("Active project: " + activeProjectId);
  }

  var SECOND_COMMERCIAL_FALLBACK_ID = "cproj_eadc72d001ca";

  function findSecondCommercialProject(rows) {
    var list = rows || projectRowsCache || [];
    return list.find(function (row) {
      var title = String(row.title || "").toLowerCase();
      return title.indexOf("second commercial") !== -1 || row.id === SECOND_COMMERCIAL_FALLBACK_ID;
    }) || null;
  }

  async function ensureSecondCommercialSelected() {
    // Always refresh so we never trust a stale empty cache or a dead localStorage id.
    try {
      await refreshProjects();
    } catch (err) {
      // Keep going with whatever cache we have; caller shows a clear banner.
    }
    var match = findSecondCommercialProject(projectRowsCache);
    if (match) {
      setActiveProjectId(match.id);
      try { await refreshAssets(); } catch (err2) { /* non-fatal */ }
      return match.id;
    }
    if (activeProjectId && projectRowsCache.some(function (row) { return row.id === activeProjectId; })) {
      updateActiveProjectLabel();
      return activeProjectId;
    }
    var fallback = projectRowsCache.find(function (row) {
      return row.project_type === "promo_video" || Number(row.duration_target) === 30;
    }) || projectRowsCache[0] || null;
    if (!fallback) return null;
    setActiveProjectId(fallback.id);
    try { await refreshAssets(); } catch (err3) { /* non-fatal */ }
    return fallback.id;
  }

  function $(id) { return document.getElementById(id); }
  async function checkGenovaAvatarReadiness() {
    var target = $("genova-avatar-readiness-result");
    var button = $("check-genova-avatar-readiness");
    if (!target || !button) return;
    var projectId = activeProjectId;
    var revision = activeProjectRevision;
    if (!projectId) {
      target.textContent = "Select an AMICOR 30-second project first. No provider request made.";
      return;
    }
    button.disabled = true;
    target.textContent = "Checking saved presenter and provider settings (no paid generation)...";
    try {
      var state = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/genova-avatar-readiness");
      if (activeProjectId !== projectId || activeProjectRevision !== revision) return;
      target.textContent =
        "Genova image: " + (state.approved_presenter_image_found ? "found" : "not found") +
        " | Kling: " + (state.provider_status || "unknown") +
        " | Approved narration audio: " + (state.approved_narration_audio_found ? "found" : "not ready") +
        " | Estimate confirmation: " + (state.budget_confirmation_valid ? "current" : "not ready") +
        " | Spending gate: " + (state.budget_enforcement_ready ? "ready" : "not ready") +
        " | Paid generation: " + (state.can_generate ? "requires separate owner action" : "blocked") +
        ". No paid request submitted." +
        (state.presenter_image_next_step ? " Image guidance: " + state.presenter_image_next_step : "") +
        (state.narration_next_step ? " Narration: " + state.narration_next_step : "") +
        (state.reason ? " " + state.reason : "");
    } catch (err) {
      if (activeProjectId !== projectId || activeProjectRevision !== revision) return;
      target.textContent = "Genova readiness check unavailable: " + (err && err.message ? err.message : "unknown error");
    } finally { if (activeProjectRevision === revision) button.disabled = false; }
  }

  var genovaReadinessButton = $("check-genova-avatar-readiness");
  if (genovaReadinessButton) genovaReadinessButton.addEventListener("click", checkGenovaAvatarReadiness);

  async function genovaImageChoices() {
    var target = $("genova-image-choices");
    if (!target || !activeProjectId) { if (target) target.textContent = "Select a project first."; return; }
    target.textContent = "Loading project images...";
    var p = activeProjectId;
    var revision = activeProjectRevision;
    try {
      var state = await api("/api/nova/creative/projects/" + encodeURIComponent(p) + "/genova-avatar-readiness");
      if (activeProjectId !== p || activeProjectRevision !== revision) return;
      target.textContent = "";
      var selected = document.createElement("p");
      selected.textContent = state.approved_image_asset_id ? "Approved image: " + state.approved_image_asset_id : "No image approved yet.";
      target.appendChild(selected);
      (state.candidate_images || []).forEach(function (item) {
        var wrapper = document.createElement("div");
        wrapper.className = "actions wrap";
        var label = document.createElement("span");
        label.textContent = item.title || item.asset_id;
        var button = document.createElement("button");
        button.type = "button"; button.className = "secondary";
        button.textContent = state.approved_image_asset_id === item.asset_id ? "Approved" : "Approve this image";
        button.disabled = state.approved_image_asset_id === item.asset_id;
        button.addEventListener("click", async function () {
          if (activeProjectId !== p || activeProjectRevision !== revision) return;
          if (!window.confirm("Approve this project image as Genova presenter?")) return;
          button.disabled = true;
          try {
            await api("/api/nova/creative/projects/" + encodeURIComponent(p) + "/genova-image-approval", {
              method: "PUT", body: JSON.stringify({asset_id: item.asset_id})
            });
            if (activeProjectId === p && activeProjectRevision === revision) {
              await genovaImageChoices(); await checkGenovaAvatarReadiness();
            }
          } catch (error) { if (activeProjectRevision === revision) { target.textContent = "Approval failed: " + error.message; button.disabled = false; } }
        });
        var thumb = document.createElement("img");
        thumb.alt = "Candidate image: " + (item.title || item.asset_id);
        thumb.loading = "lazy";
        thumb.style.cssText = "width:96px;height:120px;object-fit:contain;display:block;border-radius:8px;";
        var mediaPath = "/api/nova/creative/projects/" + encodeURIComponent(p) +
          "/assets/" + encodeURIComponent(item.asset_id) + "/file";
        (async function () {
          try {
            var shared = session();
            var response = shared && shared.authFetch
              ? await shared.authFetch(mediaPath, {method:"GET"})
              : await fetch(mediaPath, {headers: {"Authorization": "Bearer " + token()}});
            if (!response.ok) throw new Error("Image unavailable");
            var blob = await response.blob();
            if (!blob.type.startsWith("image/")) throw new Error("Not image media");
            // Studio CSP permits data: images, not blob: image URLs.
            // Read only the owner-authenticated image response; never expose tokens in URLs.
            var reader = new FileReader();
            reader.onload = function () {
              if (activeProjectId !== p || !target.contains(thumb)) return;
              thumb.src = reader.result;
            };
            reader.onerror = function () { thumb.alt = "Preview unavailable: " + (item.title || "image"); };
            reader.readAsDataURL(blob);
          } catch (err) { thumb.alt = "Preview unavailable: " + (item.title || "image"); }
        })();
        wrapper.appendChild(thumb); wrapper.appendChild(label); wrapper.appendChild(button); target.appendChild(wrapper);
      });
      if (!(state.candidate_images || []).length) target.appendChild(document.createTextNode("No eligible generated image assets in this project."));
    } catch (error) { if (activeProjectRevision === revision) target.textContent = "Could not load images: " + error.message; }
  }
  var genovaUpload = $("genova-upload-image");
  async function genovaNarrationChoices() {
    var target = $("genova-narration-choices");
    var p = activeProjectId;
    if (!target || !p) { if (target) target.textContent = "Select a project first."; return; }
    target.textContent = "Loading saved narration...";
    try {
      var state = await api("/api/nova/creative/projects/" + encodeURIComponent(p) + "/genova-narration");
      if (activeProjectId !== p) return;
      target.textContent = state.message;
      (state.candidate_audio || []).forEach(function (item) {
        var row = document.createElement("div"); row.className = "actions wrap";
        var title = document.createElement("span"); title.textContent = item.title + (item.matches_saved_script === false ? " — does not match the latest saved presenter script" : "");
        var listen = document.createElement("button"); listen.type = "button"; listen.className = "secondary";
        listen.textContent = "Download narration to review";
        listen.addEventListener("click", async function () {
          if (activeProjectId !== p) return;
          try { await downloadProtectedAsset("/api/nova/creative/projects/" + encodeURIComponent(p) + "/assets/" + encodeURIComponent(item.asset_id) + "/file", item.filename || "genova-narration.wav"); }
          catch (error) { showBanner(error.message, false); }
        });
        var approve = document.createElement("button"); approve.type = "button"; approve.className = "secondary";
        approve.textContent = state.approved_asset_id === item.asset_id ? "Narration approved" : "Approve narration";
        approve.disabled = state.approved_asset_id === item.asset_id || item.matches_saved_script === false;
        approve.addEventListener("click", async function () {
          if (activeProjectId !== p || !window.confirm("Have you listened to this narration and approved its voice, words and timing for this project?")) return;
          approve.disabled = true;
          try {
            await api("/api/nova/creative/projects/" + encodeURIComponent(p) + "/genova-narration-approval", {method: "PUT", body: JSON.stringify({asset_id: item.asset_id})});
            if (activeProjectId === p) { await genovaNarrationChoices(); await checkGenovaAvatarReadiness(); }
          } catch (error) { if (activeProjectId === p) { target.textContent = "Narration approval failed: " + error.message; approve.disabled = false; } }
        });
        row.appendChild(title); row.appendChild(listen); row.appendChild(approve); target.appendChild(row);
      });
      if (!(state.candidate_audio || []).length) target.appendChild(document.createTextNode(" No saved narration is available in this project."));
    } catch (error) { if (activeProjectId === p) target.textContent = "Could not load narration: " + error.message; }
  }
  var narrationUpload = $("genova-upload-narration");
  if (narrationUpload) narrationUpload.addEventListener("click", async function () {
    var p = activeProjectId;
    var input = $("genova-narration-file");
    var file = input && input.files && input.files[0];
    var script = ($("genova-narration-script").value || "").trim();
    if (!p || !file || !script) { showBanner("Select a project, recording and its exact script first.", false); return; }
    if (!file.size || file.size > 32 * 1024 * 1024) { showBanner("Choose audio under 32 MB.", false); return; }
    narrationUpload.disabled = true;
    try {
      var form = new FormData(); form.append("file", file); form.append("script", script);
      var shared = session();
      var path = "/api/nova/creative/projects/" + encodeURIComponent(p) + "/genova-narration-upload";
      var response = shared && shared.authFetch
        ? await shared.authFetch(path, {method: "POST", body: form})
        : await fetch(path, {method: "POST", headers: {"Authorization": "Bearer " + token()}, body: form});
      if (!response.ok) {
        var detail = await response.json().catch(function () { return {}; });
        throw new Error(typeof detail.detail === "string" ? detail.detail : "Upload rejected (" + response.status + ")");
      }
      if (activeProjectId !== p) return;
      showBanner("Narration and script imported. Listen and approve separately. No generation started.", true);
      await genovaNarrationChoices(); await checkGenovaAvatarReadiness(); await refreshAssets();
    } catch (error) { if (activeProjectId === p) showBanner("Narration import failed: " + error.message, false); }
    finally { narrationUpload.disabled = false; }
  });
  var narrationLoad = $("genova-load-narration");
  if (narrationLoad) narrationLoad.addEventListener("click", genovaNarrationChoices);
  var narrationRevoke = $("genova-revoke-narration");
  if (narrationRevoke) narrationRevoke.addEventListener("click", async function () {
    var p = activeProjectId;
    if (!p || !window.confirm("Remove narration approval for this project?")) return;
    try {
      await api("/api/nova/creative/projects/" + encodeURIComponent(p) + "/genova-narration-approval", {method: "PUT", body: JSON.stringify({asset_id: null})});
      if (activeProjectId === p) { await genovaNarrationChoices(); await checkGenovaAvatarReadiness(); }
    } catch (error) { showBanner("Could not remove narration approval: " + error.message, false); }
  });
  if (genovaUpload) genovaUpload.addEventListener("click", async function () {
    var input = $("genova-image-file");
    var file = input && input.files && input.files[0];
    if (!activeProjectId || !file) { showBanner("Select a project and image first.", false); return; }
    if (file.size > 8 * 1024 * 1024) { showBanner("Choose an image under 8 MB.", false); return; }
    genovaUpload.disabled = true;
    try {
      var form = new FormData();
      form.append("file", file);
      var shared = session();
      var path = "/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/genova-image-upload";
      var response = shared && shared.authFetch
        ? await shared.authFetch(path, {method: "POST", body: form})
        : await fetch(path, {method: "POST", headers: {"Authorization": "Bearer " + token()}, body: form});
      if (!response.ok) throw new Error("Upload rejected (" + response.status + ")");
      showBanner("Image uploaded. Review it below, then approve explicitly.", true);
      await genovaImageChoices();
    } catch (error) { showBanner("Image upload failed: " + error.message, false); }
    finally { genovaUpload.disabled = false; }
  });
  var genovaLoad = $("genova-load-images");
  if (genovaLoad) genovaLoad.addEventListener("click", genovaImageChoices);
  var genovaRevoke = $("genova-revoke-image");
  if (genovaRevoke) genovaRevoke.addEventListener("click", async function () {
    if (!activeProjectId || !window.confirm("Remove Genova image approval?")) return;
    try {
      await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/genova-image-approval", {method:"PUT", body: JSON.stringify({asset_id:null})});
      await genovaImageChoices(); await checkGenovaAvatarReadiness();
    } catch (error) { showBanner("Could not remove approval: " + error.message, false); }
  });

  function session() { return window.AmiCorSession || null; }
  function token() {
    var shared = session();
    if (shared && typeof shared.getAccessToken === "function") {
      var current = shared.getAccessToken();
      if (current) return current;
    }
    return localStorage.getItem(tokenKey) || "";
  }
  function setToken(value) {
    if (value) localStorage.setItem(tokenKey, value);
    else localStorage.removeItem(tokenKey);
  }
  function showBanner(message, ok) {
    var el = $("banner");
    el.textContent = message;
    el.classList.remove("hidden");
    el.classList.toggle("error", !ok);
  }
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function loadImage(src) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error("Could not load image for branded export.")); };
      img.src = src;
    });
  }
  function presenterMarkedPublishReady(meta) {
    meta = meta || {};
    if (meta.publish_ready !== true) return false;
    if (String(meta.quality_state || "").toUpperCase() === "PREVIEW_ONLY") return false;
    if (meta.provider_watermark_preserved === true) return false;
    var provider = meta.provider_result || {};
    if (provider.watermark_free === false) return false;
    if (String(provider.quality_state || "").toUpperCase() === "PREVIEW_ONLY") return false;
    return true;
  }
  function memoryHeadroomNotice(row) {
    var meta = (row && row.metadata) || {};
    var provider = meta.provider_result || {};
    var loudness = provider.loudness || {};
    var text = String(meta.caption_render_error || loudness.normalization_error || "");
    if (text.toLowerCase().indexOf("insufficient server memory headroom") === -1) return "";
    return "<p class=\"hint memory-notice\">Nova paused extra video processing because server memory was tight. Your existing presenter video is still available to preview and download.</p>";
  }
  function clickVerified(meta) {
    var click = meta && meta.website_field_url ? meta : (meta && meta.click_destination);
    if (!click || click.verified !== true) return false;
    if (click.classification !== "first_party_nova") return false;
    var status = Number(click.http_status);
    if (!(status >= 200 && status < 300)) return false;
    var url = String(click.website_field_url || "");
    return url.indexOf("https://getamicor.com/nova-today/") === 0 &&
      url.indexOf("utm_campaign=nova_30s_commercial") >= 0;
  }
  function commercialComplete(meta) {
    meta = meta || {};
    if (meta.commercial_complete !== true) return false;
    if (String(meta.quality_state || "").toUpperCase() === "PREVIEW_ONLY") return false;
    if (meta.pipeline !== "presenter_30s") return false;
    if (meta.presenter_used !== true || meta.presenter === false) return false;
    if (meta.lip_sync !== true) return false;
    if (meta.illustrated_fallback === true || meta.commercial_slideshow === true) return false;
    if (meta.render_mode === "offline_montage_not_lipsync") return false;
    if (meta.true_ai_motion_synthesis !== true && meta.real_motion !== true) return false;
    if (String(meta.visual_mode || "") === "illustrated_fallback" || String(meta.visual_mode || "") === "title_cards") return false;
    var narration = meta.narration || {};
    var engine = String(narration.engine || meta.narration_engine || "").toLowerCase();
    if (engine.indexOf("espeak") >= 0) return false;
    if (String(narration.license || meta.voice_license || "").toUpperCase().indexOf("GPL") >= 0) return false;
    if (String(meta.license_status || "").toUpperCase() !== "GREEN") return false;
    if (meta.provider_clearance !== true) return false;
    return true;
  }
  function assetFailureHtml(row) {
    if (String(row.status || "").toUpperCase() !== "ERROR") return "";
    var provider = (row.metadata || {}).provider_result || {};
    var message = String(provider.message || "Generation failed. No provider reason was saved.");
    // Older provider errors may contain inline artwork or authorization text.
    message = message.replace(/data:image\/[^\s"']+/gi, "[source image]")
      .replace(/\b(Bearer|Key)\s+[A-Za-z0-9._:\/-]+/g, "$1 [redacted]")
      .replace(/\b(?:sk-|key_)[A-Za-z0-9_-]+/g, "[redacted]");
    return "<p class=\"error asset-failure\"><strong>Generation failed:</strong> " +
      escapeHtml(message.slice(0, 2000)) + "</p>";
  }
  function assertDownloadUrlHasNoToken(url) {
    var text = String(url || "");
    if (/[?&](access_token|token|authorization)=/i.test(text) || /bearer\s+[A-Za-z0-9._~+/-]+=*/i.test(text)) {
      throw new Error("Refusing to put an access token in the download URL.");
    }
  }
  function filenameFromDisposition(header, fallback) {
    var value = String(header || "");
    var star = /filename\*=UTF-8''([^;]+)/i.exec(value);
    if (star) {
      try { return decodeURIComponent(star[1].trim()); } catch (err) { return star[1].trim(); }
    }
    var plain = /filename="([^"]+)"/i.exec(value) || /filename=([^;]+)/i.exec(value);
    if (plain) return plain[1].trim().replace(/^"|"$/g, "");
    return fallback || "download";
  }
  async function downloadProtectedAsset(assetUrl, fallbackName) {
    assertDownloadUrlHasNoToken(assetUrl);
    var headers = {};
    var shared = session();
    if (shared && typeof shared.ensureReady === "function") {
      try { await shared.ensureReady(); } catch (err) { /* a failed refresh still uses the current bearer below */ }
    }
    var currentToken = token();
    if (currentToken) headers.Authorization = "Bearer " + currentToken;
    var res;
    if (shared && typeof shared.authFetch === "function") {
      res = await shared.authFetch(assetUrl, { method: "GET", headers: headers });
    } else {
      res = await fetch(assetUrl, { method: "GET", headers: headers });
    }
    var contentType = "";
    if (res.headers && typeof res.headers.get === "function") {
      contentType = String(res.headers.get("content-type") || "");
    }
    if (res.status === 401) {
      setToken("");
      if (shared && typeof shared.clear === "function") shared.clear("studio_download_unauthorized");
      setSignedIn(false);
      throw new Error("Session expired. Sign in again. (401)");
    }
    if (res.status === 403) throw new Error("Access denied. (403)");
    if (res.status === 404) throw new Error("Not found. Check the selected project. (404)");
    if (!res.ok || contentType.indexOf("application/json") >= 0 || contentType.indexOf("text/html") >= 0) {
      var errBody = null;
      try { errBody = await res.json(); } catch (err) { errBody = null; }
      var detail = errBody && typeof errBody.detail === "string" ? errBody.detail : "";
      if (!detail && errBody && errBody.detail && errBody.detail.message) detail = String(errBody.detail.message);
      throw new Error(detail || ("Download failed. (" + res.status + ")"));
    }
    var blob = await res.blob();
    if (!blob || !blob.size) throw new Error("Download was empty.");
    var mime = (contentType.split(";")[0] || blob.type || "application/octet-stream").trim();
    if (mime && blob.type !== mime) blob = new Blob([blob], { type: mime });
    var disposition = res.headers && typeof res.headers.get === "function" ? res.headers.get("content-disposition") : "";
    var fileName = filenameFromDisposition(disposition, fallbackName || "download");
    var objectUrl = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = objectUrl;
    link.download = fileName;
    document.body.appendChild(link);
    try {
      link.click();
    } finally {
      link.remove();
      setTimeout(function () { URL.revokeObjectURL(objectUrl); }, 1500);
    }
    return { fileName: fileName, mime: mime };
  }
  async function downloadBrandedImage(imageUrl, fileStem) {
    var artwork = await loadImage(imageUrl);
    var logo = await loadImage("/static/branding/amicor-logo-full.png");
    var canvas = document.createElement("canvas");
    canvas.width = artwork.naturalWidth || artwork.width;
    canvas.height = artwork.naturalHeight || artwork.height;
    var ctx = canvas.getContext("2d");
    ctx.drawImage(artwork, 0, 0, canvas.width, canvas.height);

    var targetWidth = Math.max(140, Math.round(canvas.width * 0.28));
    var targetHeight = Math.max(1, Math.round(targetWidth * ((logo.naturalHeight || logo.height) / Math.max(1, logo.naturalWidth || logo.width))));
    var margin = Math.max(18, Math.round(canvas.width * 0.025));
    var padX = Math.max(12, Math.round(targetWidth * 0.06));
    var padY = Math.max(10, Math.round(targetHeight * 0.14));

    ctx.save();
    ctx.fillStyle = "rgba(255,255,255,0.92)";
    ctx.beginPath();
    var x = margin - padX, y = margin - padY, w = targetWidth + (padX * 2), h = targetHeight + (padY * 2);
    var r = Math.max(8, Math.round(Math.min(w, h) * 0.08));
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
    else ctx.rect(x, y, w, h);
    ctx.fill();
    ctx.restore();

    ctx.drawImage(logo, margin, margin, targetWidth, targetHeight);
    var link = document.createElement("a");
    link.download = (fileStem || "amicor-nova") + "-branded.png";
    link.href = canvas.toDataURL("image/png");
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function createPromoVideo(imageUrl, fileStem) {
    if (!window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream) {
      throw new Error("This browser does not support local video export.");
    }
    var artwork = await loadImage(imageUrl);
    var logo = await loadImage("/static/branding/amicor-logo-full.png");
    var canvas = document.createElement("canvas");
    canvas.width = artwork.naturalWidth || artwork.width;
    canvas.height = artwork.naturalHeight || artwork.height;
    var ctx = canvas.getContext("2d");
    var durationMs = 8000;
    var fps = 30;
    var stream = canvas.captureStream(fps);
    var candidates = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
    var mime = "";
    if (MediaRecorder.isTypeSupported) {
      for (var i = 0; i < candidates.length; i += 1) {
        if (MediaRecorder.isTypeSupported(candidates[i])) {
          mime = candidates[i];
          break;
        }
      }
    }
    var recorder;
    try {
      recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    } catch (err) {
      throw new Error("This browser cannot start local WebM video recording.");
    }
    var chunks = [];
    recorder.ondataavailable = function (event) {
      if (event.data && event.data.size) chunks.push(event.data);
    };
    var done = new Promise(function (resolve, reject) {
      recorder.onerror = function () { reject(new Error("Video recording failed.")); };
      recorder.onstop = function () { resolve(new Blob(chunks, { type: mime })); };
    });

    function drawFrame(progress) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      var zoom = 1 + (0.035 * progress);
      var drawW = canvas.width * zoom;
      var drawH = canvas.height * zoom;
      var dx = (canvas.width - drawW) / 2;
      var dy = (canvas.height - drawH) / 2;
      ctx.drawImage(artwork, dx, dy, drawW, drawH);

      var targetWidth = Math.max(140, Math.round(canvas.width * 0.22));
      var targetHeight = Math.max(1, Math.round(targetWidth * ((logo.naturalHeight || logo.height) / Math.max(1, logo.naturalWidth || logo.width))));
      var margin = Math.max(24, Math.round(canvas.width * 0.035));
      var padX = Math.max(10, Math.round(targetWidth * 0.05));
      var padY = Math.max(8, Math.round(targetHeight * 0.12));
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.fillRect(margin - padX, margin - padY, targetWidth + (padX * 2), targetHeight + (padY * 2));
      ctx.drawImage(logo, margin, margin, targetWidth, targetHeight);
    }

    recorder.start(250);
    var start = performance.now();
    await new Promise(function (resolve) {
      function tick(now) {
        var progress = Math.min(1, (now - start) / durationMs);
        drawFrame(progress);
        if (progress < 1) requestAnimationFrame(tick);
        else resolve();
      }
      requestAnimationFrame(tick);
    });
    recorder.stop();
    var blob = await done;
    if (!blob || !blob.size) {
      throw new Error("Video recording finished but produced an empty file.");
    }
    return {
      blob: blob,
      fileName: (fileStem || "amicor-nova") + "-promo.webm"
    };
  }

  function showPromoVideoDownload(result) {
    var old = document.getElementById("promo-video-result");
    if (old) old.remove();

    var url = URL.createObjectURL(result.blob);
    var wrap = document.createElement("div");
    wrap.id = "promo-video-result";
    wrap.className = "item";

    var video = document.createElement("video");
    video.controls = true;
    video.playsInline = true;
    video.src = url;
    video.style.maxWidth = "100%";
    video.style.display = "block";
    video.style.marginBottom = "10px";

    var link = document.createElement("a");
    link.href = url;
    link.download = result.fileName;
    link.textContent = "Download video";
    link.className = "button secondary";

    wrap.appendChild(video);
    wrap.appendChild(link);
    $("asset-list").prepend(wrap);

    setTimeout(function () {
      if (!document.body.contains(wrap)) URL.revokeObjectURL(url);
    }, 600000);
    return link;
  }


  function loadVideo(src) {
    return new Promise(function (resolve, reject) {
      var video = document.createElement("video");
      video.playsInline = true;
      video.preload = "auto";
      video.muted = true;
      video.onloadedmetadata = function () { resolve(video); };
      video.onerror = function () { reject(new Error("Could not load one of the generated scene videos.")); };
      video.src = src;
      video.load();
    });
  }

  function loadAudio(src) {
    return new Promise(function (resolve, reject) {
      var audio = document.createElement("audio");
      audio.preload = "auto";
      audio.onloadedmetadata = function () { resolve(audio); };
      audio.onerror = function () { reject(new Error("Could not load the generated Nova voice track.")); };
      audio.src = src;
      audio.load();
    });
  }

  function sceneIndexFromAsset(row) {
    var metadata = row.metadata || {};
    var direct = Number(metadata.scene_index);
    if (Number.isFinite(direct)) return direct;
    var provider = metadata.provider_result || {};
    var brief = provider.brief || {};
    var nested = Number(brief.scene_index);
    return Number.isFinite(nested) ? nested : 9999;
  }

  async function buildFinalPromo(detail) {
    if (!window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream) {
      throw new Error("This browser does not support final promo recording.");
    }

    var assets = detail.assets || [];
    var clips = assets.filter(function (row) {
      return row.kind === "video" && row.url && String(row.status || "").toUpperCase() === "GENERATED";
    }).sort(function (a, b) {
      return sceneIndexFromAsset(a) - sceneIndexFromAsset(b);
    });
    var artwork = assets.filter(function (row) {
      return row.kind === "image" && row.url && String(row.status || "").toUpperCase() === "GENERATED";
    });

    if (!clips.length && !artwork.length) {
      throw new Error("Generate at least one AI scene or image before building the final promo.");
    }

    var audioAssets = assets.filter(function (row) {
      return row.kind === "audio" && row.url && String(row.status || "").toUpperCase() === "GENERATED";
    });
    var voiceAsset = audioAssets.length ? audioAssets[audioAssets.length - 1] : null;

    var firstVideo = clips.length ? await loadVideo(clips[0].url) : null;
    var firstImage = !clips.length ? await loadImage(artwork[0].url) : null;
    var logo = await loadImage("/static/branding/amicor-logo-full.png");
    var canvas = document.createElement("canvas");
    canvas.width = firstVideo ? (firstVideo.videoWidth || 1280) : (firstImage.naturalWidth || firstImage.width || 1280);
    canvas.height = firstVideo ? (firstVideo.videoHeight || 720) : (firstImage.naturalHeight || firstImage.height || 720);
    var ctx = canvas.getContext("2d");
    var fps = 30;
    var canvasStream = canvas.captureStream(fps);

    var audioContext = null;
    var audioElement = null;
    var audioDestination = null;
    var outputTracks = canvasStream.getVideoTracks().slice();

    if (voiceAsset) {
      audioElement = await loadAudio(voiceAsset.url);
      var AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        audioContext = new AudioCtx();
        if (audioContext.state === "suspended") await audioContext.resume();
        audioDestination = audioContext.createMediaStreamDestination();
        var source = audioContext.createMediaElementSource(audioElement);
        source.connect(audioDestination);
        source.connect(audioContext.destination);
        Array.prototype.push.apply(outputTracks, audioDestination.stream.getAudioTracks());
      }
    }

    var outputStream = new MediaStream(outputTracks);
    var candidates = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"];
    var mime = "";
    if (MediaRecorder.isTypeSupported) {
      for (var i = 0; i < candidates.length; i += 1) {
        if (MediaRecorder.isTypeSupported(candidates[i])) {
          mime = candidates[i];
          break;
        }
      }
    }
    var recorder = mime ? new MediaRecorder(outputStream, { mimeType: mime }) : new MediaRecorder(outputStream);
    var chunks = [];
    recorder.ondataavailable = function (event) {
      if (event.data && event.data.size) chunks.push(event.data);
    };
    var stopped = new Promise(function (resolve, reject) {
      recorder.onerror = function () { reject(new Error("Final promo recording failed.")); };
      recorder.onstop = function () { resolve(); };
    });

    function drawLogo() {
      var targetWidth = Math.max(130, Math.round(canvas.width * 0.22));
      var targetHeight = Math.max(1, Math.round(targetWidth * ((logo.naturalHeight || logo.height) / Math.max(1, logo.naturalWidth || logo.width))));
      var margin = Math.max(20, Math.round(canvas.width * 0.03));
      var padX = Math.max(10, Math.round(targetWidth * 0.05));
      var padY = Math.max(8, Math.round(targetHeight * 0.12));
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.fillRect(margin - padX, margin - padY, targetWidth + padX * 2, targetHeight + padY * 2);
      ctx.drawImage(logo, margin, margin, targetWidth, targetHeight);
    }

    function drawCover(image) {
      var iw = image.naturalWidth || image.width;
      var ih = image.naturalHeight || image.height;
      var scale = Math.max(canvas.width / iw, canvas.height / ih);
      var w = iw * scale;
      var h = ih * scale;
      ctx.drawImage(image, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h);
    }

    async function playClip(row, existingVideo) {
      var video = existingVideo || await loadVideo(row.url);
      video.currentTime = 0;
      video.muted = true;
      await video.play();
      await new Promise(function (resolve) {
        function draw() {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          drawLogo();
          if (video.ended || video.paused) resolve();
          else requestAnimationFrame(draw);
        }
        requestAnimationFrame(draw);
      });
      video.pause();
    }

    async function playArtwork(row, existingImage, durationMs) {
      var image = existingImage || await loadImage(row.url);
      var started = performance.now();
      await new Promise(function (resolve) {
        function draw(now) {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          drawCover(image);
          drawLogo();
          if ((now - started) >= durationMs) resolve();
          else requestAnimationFrame(draw);
        }
        requestAnimationFrame(draw);
      });
    }

    recorder.start(250);
    if (audioElement) {
      audioElement.currentTime = 0;
      await audioElement.play();
    }

    if (clips.length) {
      for (var clipIndex = 0; clipIndex < clips.length; clipIndex += 1) {
        await playClip(clips[clipIndex], clipIndex === 0 ? firstVideo : null);
      }
    } else {
      var targetMs = audioElement && isFinite(audioElement.duration) && audioElement.duration > 0
        ? Math.max(3000, (audioElement.duration * 1000) / artwork.length)
        : 5000;
      for (var artIndex = 0; artIndex < artwork.length; artIndex += 1) {
        await playArtwork(artwork[artIndex], artIndex === 0 ? firstImage : null, targetMs);
        if (audioElement && audioElement.ended) break;
      }
    }

    if (audioElement && !audioElement.ended) {
      await new Promise(function (resolve) {
        function holdLastFrame() {
          drawLogo();
          if (audioElement.ended) resolve();
          else requestAnimationFrame(holdLastFrame);
        }
        requestAnimationFrame(holdLastFrame);
      });
    }

    recorder.stop();
    await stopped;
    if (audioElement) audioElement.pause();
    if (audioContext) await audioContext.close();

    var blob = new Blob(chunks, { type: mime || "video/webm" });
    if (!blob.size) throw new Error("Final promo recording produced an empty file.");
    return {
      blob: blob,
      fileName: clips.length ? "amicor-nova-final-promo.webm" : "amicor-nova-slideshow-preview.webm",
      clipCount: clips.length,
      artworkCount: artwork.length,
      hasVoice: Boolean(voiceAsset),
      renderMode: clips.length ? "browser_scene_clips" : "browser_artwork_slideshow",
      commercial_slideshow: !clips.length,
      acceptance_note: clips.length
        ? "Browser WebM is a review helper; prefer the server MP4 export for commercial acceptance."
        : "Still slideshow preview only — not commercial acceptance."
    };
  }

  function showFinalPromoDownload(result) {
    var old = document.getElementById("final-promo-result");
    if (old) old.remove();
    var url = URL.createObjectURL(result.blob);
    var wrap = document.createElement("div");
    wrap.id = "final-promo-result";
    wrap.className = "item";

    var title = document.createElement("strong");
    title.textContent = "Final AMICOR Nova promo";
    var meta = document.createElement("div");
    meta.className = "muted";
    var visualCount = result.clipCount || result.artworkCount || 0;
    var visualLabel = result.clipCount ? " AI scene clip(s)" : " artwork scene(s)";
    meta.textContent = visualCount + visualLabel + (result.hasVoice ? " · Nova voice included" : " · no voice track") +
      (result.renderMode === "browser_artwork_slideshow" ? " · browser-safe render" : "");

    var video = document.createElement("video");
    video.controls = true;
    video.playsInline = true;
    video.src = url;
    video.style.maxWidth = "100%";
    video.style.display = "block";
    video.style.margin = "10px 0";

    var link = document.createElement("a");
    link.href = url;
    link.download = result.fileName;
    link.textContent = "Download final promo";
    link.className = "button secondary";

    wrap.appendChild(title);
    wrap.appendChild(meta);
    wrap.appendChild(video);
    wrap.appendChild(link);
    $("asset-list").prepend(wrap);
    link.focus();

    setTimeout(function () {
      if (!document.body.contains(wrap)) URL.revokeObjectURL(url);
    }, 600000);
  }

  function detailText(body, fallback) {
    if (!body) return fallback;
    var detail = body.detail;
    if (detail && typeof detail === "object") {
      if (detail.message) return String(detail.message);
      if (Array.isArray(detail) && detail.length) {
        return detail.map(function (item) {
          if (!item) return "";
          if (typeof item === "string") return item;
          return item.msg || item.message || JSON.stringify(item);
        }).filter(Boolean).join("; ") || fallback;
      }
      try { return JSON.stringify(detail); } catch (err) { return fallback; }
    }
    if (typeof detail === "string" && detail) return detail;
    if (body.message) return String(body.message);
    return fallback;
  }
  async function api(path, options) {
    options = options || {};
    var isLogin = path === "/api/auth/login";
    var headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    var res;
    try {
      var shared = (typeof window !== "undefined" && window.AmiCorSession) ? window.AmiCorSession : null;
      if (!isLogin && shared && typeof shared.ensureReady === "function") {
        await shared.ensureReady();
      }
      if (!isLogin && shared && typeof shared.authFetch === "function") {
        res = await shared.authFetch(path, Object.assign({}, options, { headers: headers }));
      } else {
        if (!isLogin && typeof token === "function" && token()) headers.Authorization = "Bearer " + token();
        res = await fetch(path, Object.assign({}, options, { headers: headers }));
      }
    } catch (err) {
      var networkError = new Error("Network error. Check your connection and try again.");
      networkError.retryable = true;
      throw networkError;
    }
    var body = null;
    try { body = await res.json(); } catch (err) { body = null; }
    if (res.status === 401) {
      if (isLogin) throw new Error("Sign-in failed. " + detailText(body, "Check your email and password.") + " (401)");
      if (typeof setToken === "function") setToken("");
      var currentSession = (typeof window !== "undefined" && window.AmiCorSession) ? window.AmiCorSession : null;
      if (currentSession && typeof currentSession.clear === "function") currentSession.clear("studio_unauthorized");
      if (typeof setSignedIn === "function") setSignedIn(false);
      if (typeof $ === "function" && $("login-form")) $("login-form").classList.remove("hidden");
      throw new Error("Session expired. Sign in again. (401)");
    }
    if (res.status === 403) throw new Error("Access denied. (403)");
    if (res.status === 404) throw new Error("Not found. Check the selected project. (404)");
    if (res.status === 422) throw new Error(detailText(body, "Validation failed. (422)"));
    if (res.status >= 500) {
      var serviceError = new Error(detailText(body, "Temporary system error. (" + res.status + ")"));
      serviceError.status = res.status;
      serviceError.retryable = true;
      throw serviceError;
    }
    if (!res.ok) {
      throw new Error(detailText(body, "Request failed. (" + res.status + ")"));
    }
    return body;
  }

  async function uploadBrowserFinalPromo(projectId, result) {
    var form = new FormData();
    form.append("file", result.blob, result.fileName || "amicor-nova-final-promo.webm");
    var path = "/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/assets/browser-final-promo";
    var shared = (typeof window !== "undefined" && window.AmiCorSession) ? window.AmiCorSession : null;
    var res;
    if (shared && typeof shared.ensureReady === "function") await shared.ensureReady();
    if (shared && typeof shared.authFetch === "function") {
      res = await shared.authFetch(path, { method: "POST", body: form });
    } else {
      var headers = {};
      if (token()) headers.Authorization = "Bearer " + token();
      res = await fetch(path, { method: "POST", body: form, headers: headers });
    }
    var body = null;
    try { body = await res.json(); } catch (err) { body = null; }
    if (!res.ok) throw new Error(detailText(body, "Could not save the browser-built final promo. (" + res.status + ")"));
    return body;
  }

  function setSignedIn(on) {
    // Signed in → only Sign out. Signed out → only Sign in.
    var signInBtn = $("sign-in-toggle");
    var signOutBtn = $("sign-out");
    if (signInBtn) signInBtn.classList.toggle("hidden", !!on);
    if (signOutBtn) signOutBtn.classList.toggle("hidden", !on);
    if ($("staging-register-panel")) {
      $("staging-register-panel").style.display =
        (location.hostname === "nova-studio-validation-350.onrender.com" && !on) ? "block" : "none";
    }
    $("login-form").classList.add("hidden");
    $("session-meta").textContent = on ? "Signed in · Creative Studio" : "Sign in to use Creative Studio.";
  }
  function renderOutput(data) {
    $("output").textContent = JSON.stringify(data, null, 2);
  }
  async function refreshProviders() {
    var guards = await api("/api/nova/creative/guardrails");
    var bits = (guards.providers || []).map(function (row) {
      return row.kind + ": " + row.status + " — " + row.message;
    });
    $("provider-status").innerHTML = bits.map(function (line) {
      return "<div class=\"item\">" + escapeHtml(line) + "</div>";
    }).join("") || "No providers.";
    var ready = $("studio-test-readiness");
    if (ready) {
      var feature = guards.studio_test_feature || {};
      var checkout = feature.checkout || {};
      var pricing = feature.pricing || {};
      var walkReady = feature.walking_commercial_ready ? "Ready" : "Not ready";
      var mode = String(checkout.payment_mode || guards.STUDIO_CHECKOUT_TEST_MODE || "unconfigured");
      var price = Number(pricing.customer_price_usd || guards.STUDIO_CUSTOMER_PRICE_USD || 0).toFixed(2);
      var ceiling = Number(pricing.internal_render_cost_ceiling_usd || guards.STUDIO_RENDER_COST_CEILING_USD || 0).toFixed(2);
      ready.innerHTML =
        "<div class=\"item\"><strong>Walking commercial:</strong> " + escapeHtml(walkReady) + "</div>" +
        "<div class=\"item\"><strong>Checkout:</strong> " + escapeHtml(mode) +
        (checkout.real_test_checkout_available ? " · Stripe TEST connected" : "") + "</div>" +
        "<div class=\"item\"><strong>Customer price:</strong> $" + escapeHtml(price) +
        " · render ceiling $" + escapeHtml(ceiling) + "</div>" +
        "<div class=\"item muted\">Live billing / paid providers / publish: OFF</div>";
      if (pricing.customer_price_usd) renderStudioPricing(pricing);
    }
  }
  async function refreshProjects() {
    var body = await api("/api/nova/creative/projects");
    var rows = (body && body.projects) || (Array.isArray(body) ? body : []) || [];
    projectRowsCache = rows.slice();
    if (activeProjectId && !rows.some(function (row) { return row.id === activeProjectId; })) {
      setActiveProjectId(null);
    }
    var listEl = $("project-list");
    if (listEl) {
      listEl.innerHTML = rows.map(function (row) {
        var active = row.id === activeProjectId ? " · ACTIVE" : "";
        return "<div class=\"item\" data-id=\"" + escapeHtml(row.id) + "\"><strong>" + escapeHtml(row.title) + "</strong>" +
          "<span class=\"badge\">" + escapeHtml(row.status) + "</span>" + active +
          "<div class=\"muted\">" + escapeHtml(row.project_type) + " · " + escapeHtml(row.platform) + "</div></div>";
      }).join("") || "<p class=\"hint\">No projects yet.</p>";
      Array.prototype.forEach.call(document.querySelectorAll("#project-list .item"), function (el) {
        el.addEventListener("click", function () {
          setActiveProjectId(el.getAttribute("data-id"));
          refreshProjects();
          refreshAssets();
        });
      });
    }
    updateActiveProjectLabel();
    return rows;
  }
  async function refreshBrands() {
    var body = await api("/api/nova/creative/brands");
    $("brand-list").innerHTML = (body.brands || []).map(function (row) {
      return "<div class=\"item\" data-id=\"" + escapeHtml(row.id) + "\"><strong>" + escapeHtml(row.business_name) + "</strong>" +
        "<div class=\"muted\">" + escapeHtml(row.tagline || row.tone || "") + "</div></div>";
    }).join("") || "<p class=\"hint\">No brands yet.</p>";
    Array.prototype.forEach.call(document.querySelectorAll("#brand-list .item"), function (el) {
      el.addEventListener("click", async function () {
        activeBrandId = el.getAttribute("data-id");
        var projectId = activeProjectId;
        if (!projectId) {
          showBanner("Brand selected for new projects: " + activeBrandId, true);
          return;
        }
        try {
          await api("/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/brand", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ brand_id: activeBrandId })
          });
          showBanner("Brand attached to active project.", true);
          await refreshProjects();
          await refreshAssets();
        } catch (err) {
          showBanner(err.message || "Could not attach brand to active project.", false);
        }
      });
    });
  }
  function latestAsset(assets, kind, predicate) {
    var matches = (assets || []).filter(function (row) {
      if (row.kind !== kind) return false;
      return predicate ? predicate(row) : true;
    });
    return matches.length ? matches[matches.length - 1] : null;
  }

  function syncPresenterScript(detail) {
    var editor = $("presenter-script");
    if (!editor) return;
    var saved = latestAsset(detail.assets || [], "presenter_script", function (row) {
      return !!String(row.content || "").trim();
    });
    var text = saved ? String(saved.content) : "";
    var firstLoad = presenterScriptProjectId !== activeProjectId;
    if (firstLoad || editor.value === presenterSavedScriptValue) editor.value = text;
    presenterScriptProjectId = activeProjectId;
    presenterSavedScriptValue = text;
    editor.disabled = false;
    if (firstLoad) {
      ["save-presenter-script", "generate-presenter-voice", "preview-talking-presenter"].forEach(function (id) {
        if ($(id)) $(id).disabled = false;
      });
    }
  }

  function renderProductionReadiness(detail) {
    var target = $("production-readiness");
    if (!target) return;
    if (!detail) {
      target.innerHTML = "<div class=\"readiness-empty\">Select a project to check readiness.</div>";
      return;
    }

    if (detail.project && detail.project.project_type === "short_drama") {
      var preview = latestAsset(detail.assets || [], "video", function (row) { return row.metadata && row.metadata.short_drama; });
      target.textContent = preview && preview.url ? "PREVIEW ONLY — dialogue and captions rendered. Review lip-sync and character continuity before publishing." : "Complete motion shots and character voices, then render in Short drama creator.";
      return;
    }
    var assets = detail.assets || [];
    var brand = detail.brand || null;
    var finalVideo = latestAsset(assets, "video", function (row) {
      return !!(row.metadata && row.metadata.final_promo);
    });
    var presenter = latestAsset(assets, "presenter_video");
    var artwork = latestAsset(assets, "image");
    var audio = latestAsset(assets, "audio");
    var caption = latestAsset(assets, "caption");

    var presenterMeta = presenter && presenter.metadata || {};
    var finalVideoMeta = finalVideo && finalVideo.metadata || {};
    var presenterDemoAccepted = !!(
      finalVideo &&
      finalVideo.url &&
      (
        finalVideoMeta.render_mode === "legacy_did_demo_passthrough" ||
        finalVideoMeta.render_mode === "publish_ready_presenter_passthrough"
      ) &&
      finalVideoMeta.demo_ready === true &&
      finalVideoMeta.provider_watermark_preserved === true
    );
    var bodyLipSyncReady = !!(
      presenter &&
      presenter.url &&
      String(presenter.status || "").toUpperCase() === "GENERATED" &&
      presenterMeta.presenter_mode === "full_body" &&
      presenterMeta.body_lipsync === true
    );
    var bodyCaptionedReady = !!(
      presenter &&
      presenter.url &&
      String(presenter.status || "").toUpperCase() === "GENERATED" &&
      presenterMeta.presenter_mode === "full_body" &&
      presenterMeta.captions_burned_in === true
    );
    var illustratedPreview = finalVideoMeta.illustrated_fallback === true || finalVideoMeta.visual_mode === "illustrated_fallback";
    var localPlatePreview = finalVideoMeta.motion_engine === "local_plate_walk_illusion" || finalVideoMeta.visual_mode === "genova_photoreal_plate";
    var offlinePreview = !!(
      illustratedPreview || localPlatePreview ||
      finalVideoMeta.render_mode === "offline_montage_not_lipsync" ||
      finalVideoMeta.pipeline === "offline_title_card_fallback" ||
      (String(finalVideoMeta.quality_state || "").toUpperCase() === "PREVIEW_ONLY" && finalVideoMeta.presenter_used === false)
    );
    var presenterReady = !!(presenter && (presenterMarkedPublishReady(presenterMeta) || presenterDemoAccepted || bodyLipSyncReady || bodyCaptionedReady));
    var presenterState = !presenter ? "NOT USED" :
      (presenterMarkedPublishReady(presenterMeta) ? "PUBLISH_READY" :
        (bodyCaptionedReady ? "FULL_BODY_CAPTIONED_READY" :
          (bodyLipSyncReady ? "FULL_BODY_LIPSYNC_READY" :
            (presenterDemoAccepted ? "DEMO_READY_WITH_PROVIDER_WATERMARK" : (presenterMeta.quality_state || "PREVIEW_ONLY")))));
    var presenterCaptionsReady = !bodyLipSyncReady || bodyCaptionedReady;

    var finalIsSlideshow = !!(
      finalVideoMeta.commercial_slideshow === true ||
      finalVideoMeta.render_mode === "ffmpeg_compat_stills" ||
      finalVideoMeta.render_mode === "browser_artwork_slideshow"
    );
    var finalIsMp4 = !!(finalVideo && finalVideo.url && /\.mp4($|\?)/i.test(String(finalVideo.url)));
    var finalCaptionsOk = !!(
      finalVideoMeta.captions_burned_in === true ||
      finalVideoMeta.subtitle_url ||
      finalVideoMeta.captions_sidecar_ready
    );
    var commercialCandidate = !!(finalVideo && finalVideo.url && finalIsMp4 && !finalIsSlideshow && finalCaptionsOk && !offlinePreview);
    var clickReady = clickVerified(finalVideoMeta);
    var clickUrl = finalVideoMeta.click_destination && finalVideoMeta.click_destination.website_field_url;
    var commerciallyComplete = commercialComplete(finalVideoMeta);
    var checks = [
      { label: "Presenter", ok: presenterReady, note: presenterState, action: "preview-talking-presenter", actionLabel: presenter ? "Regenerate presenter" : "Create presenter" },
      { label: "Presenter captions", ok: presenterCaptionsReady, note: presenterCaptionsReady ? (bodyCaptionedReady ? "Burned in" : "Not required yet") : "Finalize full-body captions", action: "finalize-presenter-captions", actionLabel: "Finalize presenter captions" },
      { label: "Final video", ok: commercialCandidate, note: !finalVideo || !finalVideo.url ? "Build the 30s presenter pipeline. The offline montage is preview only." : (illustratedPreview ? "PREVIEW_ONLY illustrated fallback. Real presenter motion is not verified." : (localPlatePreview ? "PREVIEW_ONLY local image animation. Real presenter motion is not verified." : (offlinePreview ? "PREVIEW_ONLY title cards. Presenter NOT USED." : (finalIsSlideshow ? "Blocked: still slideshow" : (!finalIsMp4 ? "Need MP4 export" : (finalCaptionsOk ? "Motion MP4 ready for owner review" : "Need captions / subtitle track")))))), action: (offlinePreview || !finalVideo || !finalVideo.url) ? "build-walking-commercial" : "build-final-promo", actionLabel: (offlinePreview || !finalVideo || !finalVideo.url) ? "Build 30s presenter" : "Build Final Promo" },
      { label: "Commercial complete", ok: commerciallyComplete, note: commerciallyComplete ? "Real motion, lip-sync, clean narration, and provider clearance are on file." : "Held until real motion, lip-sync, clean narration, and provider/license clearance.", action: "build-walking-commercial", actionLabel: "Build 30s presenter" },
      { label: "Nova click destination", ok: clickReady, note: clickUrl ? (String(clickUrl) + (clickReady ? " verified" : " not yet verified")) : "Prepare the profile Website link. Captions are not clickable.", action: "prepare-nova-links", actionLabel: "Prepare Nova links" },
      { label: "Thumbnail / artwork", ok: !!(artwork && artwork.url), note: artwork && artwork.url ? "Ready" : "Generate image", action: "generate-image", actionLabel: "Generate image" },
      { label: "Voice audio", ok: !!(audio && audio.url), note: audio && audio.url ? "Ready" : "Generate voice", action: "generate-voice", actionLabel: "Generate voice" },
      { label: "Caption copy", ok: !!(caption && String(caption.content || "").trim()) || finalCaptionsOk, note: (caption || finalCaptionsOk) ? "Ready" : "Generate caption", action: "generate-caption", actionLabel: "Generate caption" },
      { label: "Brand profile", ok: !!brand, note: brand ? (brand.business_name || "Ready") : "Select or save brand", action: "brand-profile", actionLabel: "Set up brand" }
    ];

    var reviewChecks = checks.filter(function (item) { return item.label !== "Commercial complete"; });
    var allReady = reviewChecks.every(function (item) { return item.ok; });
    var summaryLabel = !allReady ? "NEEDS WORK" : (commerciallyComplete ? "COMMERCIAL COMPLETE" : "READY FOR OWNER REVIEW");
    var summaryNote = !allReady
      ? "Complete the missing or preview-only items before final publishing."
      : (commerciallyComplete
        ? "Commercial gates passed. Publishing still requires a separate owner action."
        : "Core production assets are ready for owner review. Commercial complete stays held.");
    var header = "<div class=\"readiness-summary " + (allReady ? "ready" : "needs-work") + "\">" +
      "<strong>" + summaryLabel + "</strong>" +
      "<span>" + summaryNote + "</span></div>";

    var next = reviewChecks.find(function (item) { return !item.ok; });
    if (next) {
      header += "<div class=\"next-action-card\"><strong>Next action</strong><span>" +
        escapeHtml(next.actionLabel) + "</span><button type=\"button\" class=\"secondary readiness-action\" data-next-action=\"" +
        escapeHtml(next.action) + "\">Do this next</button></div>";
    }

    target.innerHTML = header + checks.map(function (item) {
      var actionButton = !item.ok ? "<button type=\"button\" class=\"secondary readiness-action\" data-next-action=\"" +
        escapeHtml(item.action) + "\">" + escapeHtml(item.actionLabel) + "</button>" : "";
      return "<div class=\"readiness-item " + (item.ok ? "ready" : "missing") + "\">" +
        "<span class=\"readiness-dot\" aria-hidden=\"true\"></span>" +
        "<div class=\"readiness-copy\"><strong>" + escapeHtml(item.label) + "</strong><div class=\"muted\">" +
        escapeHtml(item.note) + "</div></div>" + actionButton + "</div>";
    }).join("");

    Array.prototype.forEach.call(target.querySelectorAll(".readiness-action"), function (button) {
      button.addEventListener("click", async function () {
        var action = button.getAttribute("data-next-action");
        var targetButton = null;
        if (action === "finalize-presenter-captions") {
          if (!presenter || !presenter.content) {
            showBanner("The latest full-body presenter script is unavailable. Regenerate the presenter preview first.", false);
            return;
          }
          button.disabled = true;
          showBanner("Finalizing full-body Genova captions in the cloud...", true);
          try {
            var finalized = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/presenter/cloud-finalize", {
              method: "POST",
              body: JSON.stringify({
                script: String(presenter.content || "").trim(),
                voice: presenterMeta.voice || "coral",
                captions: true
              })
            });
            renderOutput(finalized);
            var done = finalized && finalized.status === "GENERATED" && finalized.stage === "complete";
            showBanner(finalized.message || (done ? "Full-body presenter captions are ready." : "Presenter caption finalization is still processing."), done);
            await refreshAssets();
          } catch (err) {
            showBanner(err.message || "Could not finalize full-body presenter captions.", false);
          } finally {
            button.disabled = false;
          }
          return;
        }
        if (action === "build-final-promo") targetButton = $("build-final-promo");
        else if (action === "build-walking-commercial") targetButton = $("build-walking-commercial-30s");
        else if (action === "prepare-nova-links") targetButton = $("prepare-nova-links");
        else if (action === "preview-talking-presenter") targetButton = $("preview-talking-presenter");
        else if (action === "generate-image") targetButton = document.querySelector('[data-action="image"]');
        else if (action === "generate-voice") targetButton = document.querySelector('[data-action="voice"]');
        else if (action === "generate-caption") targetButton = document.querySelector('[data-action="caption"]');
        else if (action === "brand-profile") {
          var brandForm = $("brand-form");
          if (brandForm && brandForm.scrollIntoView) brandForm.scrollIntoView({ behavior: "smooth", block: "center" });
          var defaults = $("load-amicor-brand-defaults");
          if (defaults) defaults.focus();
          showBanner("Set up or select the AMICOR Nova brand profile, then return to production readiness.", true);
          return;
        }
        if (targetButton) {
          if (targetButton.scrollIntoView) targetButton.scrollIntoView({ behavior: "smooth", block: "center" });
          targetButton.click();
        }
      });
    });
  }

  var dramaLoadedProject = null;
  function fillDrama(plan) {
    $("drama-setting").value = plan.setting || "";
    $("drama-dialogue").value = plan.dialogue || "";
    (plan.characters || []).forEach(function (character, index) {
      var suffix = String(index + 1);
      $("drama-name-" + suffix).value = character.name;
      $("drama-description-" + suffix).value = character.description;
      $("drama-voice-" + suffix).value = character.voice;
    });
  }
  function refreshDrama(detail) {
    var project = detail && detail.project;
    var plan = project && project.metadata && project.metadata.short_drama;
    var isDrama = project && project.project_type === "short_drama";
    ["plan", "motion", "voices", "render"].forEach(function (action) {
      var button = $("drama-" + action);
      if (button) button.disabled = false;
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-action="script"], [data-action="storyboard"], [data-action="voice"]'), function (button) { button.disabled = !!isDrama; });
    $("build-final-promo").disabled = !!isDrama;
    if (project && project.id !== dramaLoadedProject) {
      if (plan) fillDrama(plan);
      dramaLoadedProject = project.id;
    }
    if (!project || project.project_type !== "short_drama") {
      $("drama-progress").textContent = "Create or select a Short drama project to begin.";
      return;
    }
    var shots = (detail.scenes || []).length;
    var motion = {}, voices = {};
    (detail.assets || []).forEach(function (asset) {
      if (asset.status !== "GENERATED" || !asset.url || asset.media_available === false) return;
      var metadata = asset.metadata || {};
      var provider = metadata.provider_result || {};
      if (asset.kind === "video" && provider.brief && provider.brief.scene_index) motion[provider.brief.scene_index] = true;
      if (asset.kind === "audio" && plan && metadata.drama_revision === plan.revision) voices[metadata.line_index] = true;
    });
    $("drama-progress").textContent = shots ? Object.keys(motion).length + "/" + shots + " motion shots · " + Object.keys(voices).length + "/" + shots + " dialogue voices. Final output needs lip-sync review." : "Save cast and dialogue to create your shots.";
  }
  $("drama-sample").addEventListener("click", async function () {
    try {
      fillDrama(await api("/api/nova/creative/drama/sample"));
      $("project-type").value = "short_drama";
      $("project-title").value = "The Envelope — Nova Studio";
      showBanner("Sample loaded. Create a Short drama project, then save its cast and dialogue.", true);
    } catch (error) { showBanner(error.message, false); }
  });
  ["plan", "motion", "voices", "render"].forEach(function (action) {
    var button = $("drama-" + action);
    button.addEventListener("click", async function () {
      var activeRow = projectRowsCache.find(function (row) { return row.id === activeProjectId; }) || null;
      if (!activeRow || activeRow.project_type !== "short_drama") {
        var dramaProject = projectRowsCache.find(function (row) { return row.project_type === "short_drama"; });
        if (!dramaProject) {
          $("project-type").value = "short_drama";
          $("project-title").value = $("project-title").value.trim() || "Nova Short Drama";
          showBanner("No Short drama project exists yet. I selected Short drama above; click Create project, then use this button again.", false);
          var createButton = $("project-create-btn");
          if (createButton && createButton.scrollIntoView) createButton.scrollIntoView({ behavior: "smooth", block: "center" });
          return;
        }
        setActiveProjectId(dramaProject.id);
        await refreshProjects();
        await refreshAssets();
        showBanner("Switched to Short drama project: " + dramaProject.title + ".", true);
      }
      var projectId = activeProjectId;
      button.disabled = true;
      try {
        var path = action === "motion" ? "generate/video" : "drama/" + action;
        var options = { method: "POST" };
        if (action === "plan") {
          options.body = JSON.stringify({
            setting: $("drama-setting").value.trim(), dialogue: $("drama-dialogue").value.trim(),
            characters: [1, 2].map(function (i) {
              return {name: $("drama-name-" + i).value.trim(), description: $("drama-description-" + i).value.trim(), voice: $("drama-voice-" + i).value};
            })
          });
        }
        showBanner("Short drama " + action + " in progress…", true);
        var result = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/" + path, options);
        if (result.status === "PROCESSING" && result.job) {
          var finished = false;
          for (var attempt = 0; attempt < 180; attempt += 1) {
            await new Promise(function (resolve) { setTimeout(resolve, 5000); });
            var detail = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId));
            var job = (detail.jobs || []).find(function (row) { return row.id === result.job.id; });
            if (activeProjectId === projectId) refreshDrama(detail);
            if (job && ["QUEUED", "RUNNING"].indexOf(job.status) < 0) {
              if (job.status !== "GENERATED") throw new Error(job.message || "Drama generation failed.");
              result = {status: job.status, message: job.message};
              finished = true;
              break;
            }
          }
          if (!finished) throw new Error("Generation is still processing. Refresh the project to see its saved job.");
        }
        if (result.provider && result.provider.status && result.provider.status !== "GENERATED") {
          throw new Error(result.provider.message || "Short drama provider could not generate media.");
        }
        renderOutput(result);
        showBanner(result.message || "Short drama " + action + " complete.", true);
        await refreshAssets();
      } catch (error) { showBanner(error.message, false); }
      finally { button.disabled = false; }
    });
  });

  function assetTypeLabel(row) {
    var meta = (row && row.metadata) || {};
    if (String(row.status || "").toUpperCase() === "ERROR") return "Failed attempt";
    if (row.kind === "presenter_video") {
      if (meta.presenter_mode === "full_body") return "Full-body presenter";
      if (meta.presenter_mode === "half_body") return "Half-body presenter";
      return "Headshot presenter";
    }
    if (row.kind === "video" && meta.render_mode === "offline_montage_not_lipsync") return "Offline montage, not lip sync";
    if (row.kind === "video" && meta.final_promo) return "Final demo video";
    if (row.kind === "video") return "Scene video";
    if (row.kind === "audio") return "Voice audio";
    if (row.kind === "image") return "Image";
    return row.kind || "Asset";
  }

  async function pollStudioJob(projectId, jobId) {
    var last = null;
    for (var attempt = 0; attempt < 45; attempt += 1) {
      last = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/jobs/" + encodeURIComponent(jobId));
      if (last.ready || (last.job && (last.job.status === "GENERATED" || last.job.status === "ERROR"))) return last;
      await new Promise(function (resolve) { setTimeout(resolve, 2000); });
    }
    return last;
  }

  async function refreshAssets() {
    if (!activeProjectId) {
      $("asset-list").innerHTML = "<p class=\"hint\">Select a project.</p>";
      refreshDrama(null);
      renderProductionReadiness(null);
      return;
    }
    var selectedProject = activeProjectId;
    var revision = activeProjectRevision;
    var detail = await api("/api/nova/creative/projects/" + encodeURIComponent(selectedProject));
    if (activeProjectId !== selectedProject || activeProjectRevision !== revision) return;
    var project = detail.project || {};
    if ($("presenter-script")) syncPresenterScript(detail);
    var production = (project.metadata && project.metadata.production_settings) || {};
    if ($("project-title")) $("project-title").value = project.title || "";
    if ($("project-type") && project.project_type) $("project-type").value = project.project_type;
    if ($("project-platform") && project.platform) $("project-platform").value = project.platform;
    if ($("project-duration") && project.duration_target) $("project-duration").value = String(project.duration_target);
    if ($("project-audience")) $("project-audience").value = project.audience || "";
    if ($("project-tone")) $("project-tone").value = project.tone || "";
    if ($("project-objective")) $("project-objective").value = project.objective || "";
    if ($("presenter-mode") && production.presenter_mode) $("presenter-mode").value = production.presenter_mode;
    if ($("presenter-motion-style") && production.motion_style) $("presenter-motion-style").value = production.motion_style;
    if ($("presenter-framing") && production.framing) $("presenter-framing").value = production.framing;
    if ($("presenter-output-preset") && production.output_preset) $("presenter-output-preset").value = production.output_preset;
    if ($("presenter-voice") && production.voice) $("presenter-voice").value = production.voice;
    if ($("image-aspect") && production.image_aspect) $("image-aspect").value = production.image_aspect;
    refreshDrama(detail);
    renderProductionReadiness(detail);
    $("asset-list").innerHTML = (detail.assets || []).map(function (row) {
      var media = "";
      var mediaAvailable = row.media_available !== false;
      if (row.kind === "image" && row.url && mediaAvailable) {
        var isAmicor = String(row.content || "").toUpperCase().indexOf("AMICOR") >= 0;
        var isPrivateUpload = (row.metadata || {}).source === "owner_upload" || /\/genova_upload_[^/]+$/.test(row.url);
        var imageSource = isPrivateUpload
          ? ("data-private-image-url=\"/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/assets/" + encodeURIComponent(row.id) + "/file\"")
          : ("src=\"" + escapeHtml(row.url) + "\"");
        media = "<figure class=\"generated-media\"><img " + imageSource + " alt=\"" +
          escapeHtml(row.title || "Nova generated image") + "\" loading=\"lazy\" />" +
          (isAmicor ? "<img class=\"official-brand-overlay\" src=\"/static/branding/amicor-logo-full.png\" alt=\"AMICOR official logo\" />" : "") +
          "</figure>" +
          (isAmicor ? "<button type=\"button\" class=\"secondary branded-download\" data-image-url=\"" +
            escapeHtml(row.url) + "\" data-file-stem=\"" + escapeHtml((row.title || "amicor-nova").replace(/[^A-Za-z0-9_-]+/g, "-")) +
            "\">Download branded PNG</button> <button type=\"button\" class=\"secondary promo-video\" data-image-url=\"" +
            escapeHtml(row.url) + "\" data-file-stem=\"" + escapeHtml((row.title || "amicor-nova").replace(/[^A-Za-z0-9_-]+/g, "-")) +
            "\">Create 8s branded video</button>" : "");
      } else if ((row.kind === "video" || row.kind === "presenter_video") && row.url && mediaAvailable) {
        var isPresenterVideo = row.kind === "presenter_video";
        var isBodyMotion = isPresenterVideo && row.metadata &&
          (row.metadata.presenter_mode === "half_body" || row.metadata.presenter_mode === "full_body");
        var offlineMontage = !isPresenterVideo && row.metadata && (
          row.metadata.render_mode === "offline_montage_not_lipsync" ||
          row.metadata.pipeline === "offline_title_card_fallback"
        );
        var illustratedPreview = row.metadata && (row.metadata.illustrated_fallback === true || row.metadata.visual_mode === "illustrated_fallback");
        var localAnimation = row.metadata && (row.metadata.motion_engine === "local_plate_walk_illusion" || row.metadata.visual_mode === "genova_photoreal_plate");
        var videoLabel = illustratedPreview ? "Download illustrated preview" : (localAnimation ? "Download local animation preview" : (offlineMontage
          ? "Download offline montage"
          : (isBodyMotion ? "Download body motion preview" : (isPresenterVideo ? "Download talking presenter video" : "Download AI video"))));
        var filePath = row.id
          ? ("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/assets/" + encodeURIComponent(row.id) + "/file")
          : "";
        var fallbackVideoName = offlineMontage ? "nova-offline-montage.mp4" : "nova-video.mp4";
        var downloadControl = filePath
          ? ("<button type=\"button\" class=\"secondary asset-auth-download\" data-download-url=\"" +
            escapeHtml(filePath) + "\" data-download-name=\"" + fallbackVideoName + "\">" + videoLabel + "</button>")
          : (String(row.url).indexOf("/api/") === 0 ? "" : ("<a class=\"button secondary\" href=\"" +
            escapeHtml(row.url) + "\" download>" + videoLabel + "</a>"));
        var presenterCaptionText = isPresenterVideo && !(row.metadata && row.metadata.captions_burned_in) ? String(row.content || "").trim() : "";
        var subtitleUrl = row.metadata && row.metadata.subtitle_url ? String(row.metadata.subtitle_url) : "";
        var subtitleTrack = subtitleUrl && String(subtitleUrl).indexOf("/api/") !== 0
          ? ("<track kind=\"subtitles\" srclang=\"en\" label=\"English\" src=\"" + escapeHtml(subtitleUrl) + "\" default>")
          : "";
        var captionControl = filePath && (subtitleUrl || offlineMontage)
          ? (" <button type=\"button\" class=\"secondary asset-auth-download\" data-download-url=\"" +
            escapeHtml(filePath + "?part=captions") + "\" data-download-name=\"nova-captions.srt\">Download captions</button>")
          : "";
        var licenseNote = "";
        if (illustratedPreview || localAnimation) {
          licenseNote = "<p class=\"hint\">PREVIEW_ONLY. " + (illustratedPreview ? "Illustrated fallback." : "Local image animation.") + " Real presenter motion and professional lip-sync are not verified.</p>";
        }
        if (offlineMontage) {
          var license = String((row.metadata && row.metadata.license_status) || "AMBER");
          var clearance = (row.metadata && row.metadata.narration && row.metadata.narration.commercial_use) ||
            "Local narration is not cleared for a public ad.";
          licenseNote = "<p class=\"hint\">PREVIEW_ONLY. Presenter NOT USED. Lip-sync presenter: no. Commercial-use clearance: " +
            escapeHtml(license) + ". " + escapeHtml(String(clearance)) + "</p>";
        }
        media = "<figure class=\"generated-media" + (isPresenterVideo ? " presenter-media" : "") + "\"><video controls playsinline preload=\"metadata\" src=\"" +
          escapeHtml(row.url) + "\"" +
          (isPresenterVideo ? " class=\"presenter-caption-video\" data-caption-text=\"" + escapeHtml(presenterCaptionText) + "\"" : "") +
          ">" + subtitleTrack + "</video>" +
          (isPresenterVideo ? "<div class=\"presenter-live-caption\" aria-live=\"polite\"></div>" : "") +
          "</figure>" + licenseNote + downloadControl + captionControl;
      } else if (row.kind === "audio" && row.url && mediaAvailable) {
        var audioPath = row.id
          ? ("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/assets/" + encodeURIComponent(row.id) + "/file")
          : "";
        var audioName = /\.mp3(?:$|\?)/i.test(row.url) ? "nova-voice.mp3" : "nova-voice.wav";
        var audioControl = audioPath
          ? ("<button type=\"button\" class=\"secondary asset-auth-download\" data-download-url=\"" +
            escapeHtml(audioPath) + "\" data-download-name=\"" + audioName + "\">Download voice</button>")
          : ("<a class=\"button secondary\" href=\"" + escapeHtml(row.url) + "\" download>Download voice</a>");
        var privateAudio = (row.metadata || {}).source === "owner_audio_upload";
        media = privateAudio
          ? "<p class=\"hint\">Private recording. Download voice to listen, then use the narration approval section.</p>" + audioControl
          : "<div class=\"generated-media\"><audio controls preload=\"metadata\" src=\"" +
            escapeHtml(row.url) + "\"></audio></div>" + audioControl;
      }
      return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong>" +
        "<span class=\"badge\">" + escapeHtml(row.status) + "</span>" +
        "<div class=\"muted\">" + escapeHtml(assetTypeLabel(row)) + (row.url ? (mediaAvailable ? " · media ready" : " · media missing — regenerate") : " · no media URL") + "</div>" +
        assetFailureHtml(row) + memoryHeadroomNotice(row) + media +
        "<div>" + escapeHtml(String(row.content || "").slice(0, 280)) + "</div></div>";
    }).join("") || "<p class=\"hint\">No assets yet.</p>";
    Array.prototype.forEach.call(document.querySelectorAll("#asset-list [data-private-image-url]"), function (image) {
      var projectId = activeProjectId;
      (async function () {
        try {
          var shared = session();
          var url = image.getAttribute("data-private-image-url");
          var response = shared && shared.authFetch
            ? await shared.authFetch(url, {method: "GET"})
            : await fetch(url, {headers: {"Authorization": "Bearer " + token()}});
          if (!response.ok) throw new Error("Image unavailable");
          var blob = await response.blob();
          if (!blob.type.startsWith("image/")) throw new Error("Not image media");
          var reader = new FileReader();
          reader.onload = function () {
            if (activeProjectId === projectId && $("asset-list").contains(image)) image.src = reader.result;
          };
          reader.onerror = function () { image.alt = "Preview unavailable"; };
          reader.readAsDataURL(blob);
        } catch (error) { image.alt = "Preview unavailable"; }
      })();
    });
    Array.prototype.forEach.call(document.querySelectorAll("#asset-list .presenter-caption-video"), function (video) {
      var caption = video.parentElement && video.parentElement.querySelector(".presenter-live-caption");
      if (!caption) return;
      var raw = String(video.getAttribute("data-caption-text") || "").trim();
      var chunks = raw.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [];
      chunks = chunks.map(function (part) { return part.trim(); }).filter(Boolean);
      function updatePresenterCaption() {
        if (!chunks.length || !isFinite(video.duration) || video.duration <= 0 || video.ended) {
          if (video.ended) caption.textContent = "";
          return;
        }
        var ratio = Math.max(0, Math.min(0.9999, video.currentTime / video.duration));
        var index = Math.min(chunks.length - 1, Math.floor(ratio * chunks.length));
        caption.textContent = chunks[index];
      }
      video.addEventListener("loadedmetadata", updatePresenterCaption);
      video.addEventListener("timeupdate", updatePresenterCaption);
      video.addEventListener("play", updatePresenterCaption);
      video.addEventListener("ended", function () { caption.textContent = ""; });
    });
    Array.prototype.forEach.call(document.querySelectorAll("#asset-list .asset-auth-download"), function (button) {
      button.addEventListener("click", async function () {
        button.disabled = true;
        try {
          var saved = await downloadProtectedAsset(
            button.getAttribute("data-download-url"),
            button.getAttribute("data-download-name")
          );
          showBanner("Downloaded " + saved.fileName + " (" + saved.mime + ").", true);
        } catch (err) {
          showBanner(err.message || "Download failed.", false);
        } finally {
          button.disabled = false;
        }
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll("#asset-list .branded-download"), function (button) {
      button.addEventListener("click", async function () {
        button.disabled = true;
        showBanner("Working: preparing branded PNG...", true);
        try {
          await downloadBrandedImage(button.getAttribute("data-image-url"), button.getAttribute("data-file-stem"));
          showBanner("Branded PNG prepared with the official AMICOR logo.", true);
        } catch (err) {
          showBanner(err.message || "Branded image export failed.", false);
        } finally {
          button.disabled = false;
        }
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll("#asset-list .promo-video"), function (button) {
      button.addEventListener("click", async function () {
        button.disabled = true;
        showBanner("Working: creating 8-second branded promo video...", true);
        try {
          var result = await createPromoVideo(button.getAttribute("data-image-url"), button.getAttribute("data-file-stem"));
          var downloadLink = showPromoVideoDownload(result);
          showBanner("Branded promo video created. Use the Download video link below to save it.", true);
          downloadLink.focus();
        } catch (err) {
          showBanner(err.message || "Promo video export failed.", false);
        } finally {
          button.disabled = false;
        }
      });
    });
  }
  var clearLegacyPreviews = $("clear-legacy-preview-videos");
  if (clearLegacyPreviews) {
    clearLegacyPreviews.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Select the project whose old presenter previews you want to clean first.", false);
        return;
      }
      if (!window.confirm("Remove old headshot presenter previews, short preview clips, failed/processing preview records, and provider-watermarked preview-only videos from this project? Current scripts, captions, storyboard, and brand settings are preserved.")) {
        return;
      }
      clearLegacyPreviews.disabled = true;
      showBanner("Working: removing old headshot and short preview videos from this project...", true);
      try {
        var result = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/assets/clear-legacy-previews", {
          method: "POST"
        });
        showBanner(
          "Cleanup complete. Removed " + String(result.deleted_asset_records || 0) +
          " old preview video record(s).",
          true
        );
        await refreshAssets();
      } catch (err) {
        showBanner(err.message || "Could not remove the old preview videos.", false);
      } finally {
        clearLegacyPreviews.disabled = false;
      }
    });
  }

  var resetMedia = $("reset-project-media");
  if (resetMedia) {
    resetMedia.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Select the project whose old videos you want to clear first.", false);
        return;
      }
      if (!window.confirm("Clear old videos and generated media from this project? Presenter clips, scene videos, images, and voice files will be removed. Script, captions, storyboard, and brief will be preserved.")) {
        return;
      }
      resetMedia.disabled = true;
      showBanner("Working: clearing old videos and generated media from this project...", true);
      try {
        var result = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/assets/reset-media", {
          method: "POST"
        });
        showBanner(
          "Cleanup complete. Removed " + String(result.deleted_asset_records || 0) +
          " old video/media record(s). Script, captions, storyboard, and brief were preserved.",
          true
        );
        await refreshAssets();
      } catch (err) {
        showBanner(err.message || "Could not clear old videos from this project.", false);
      } finally {
        resetMedia.disabled = false;
      }
    });
  }

  var clearFailed = $("clear-failed-video-assets");
  if (clearFailed) {
    clearFailed.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Select the project you want to clean first.", false);
        return;
      }
      clearFailed.disabled = true;
      try {
        var result = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/assets/clear-failed-video", {
          method: "POST"
        });
        showBanner("Cleaned " + String(result.deleted || 0) + " failed video attempt(s).", true);
        await refreshAssets();
      } catch (err) {
        showBanner(err.message || "Could not clean failed video attempts.", false);
      } finally {
        clearFailed.disabled = false;
      }
    });
  }

  async function waitForScene(projectId, jobId) {
    var consecutiveFailures = 0;
    for (var attempt = 0; attempt < 240; attempt += 1) {
      await new Promise(function (resolve) { setTimeout(resolve, 5000); });
      var detail;
      try {
        detail = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId));
        consecutiveFailures = 0;
      } catch (err) {
        if (!err.retryable) throw err;
        consecutiveFailures += 1;
        if (consecutiveFailures >= 12) {
          throw new Error("Could not reconnect to scene job " + jobId + ". Its result is unknown; refresh or click Generate Next AI Scene to check the saved job. Last status check: " + err.message);
        }
        if (activeProjectId === projectId) {
          showBanner("Scene status temporarily unavailable. Reconnecting to saved job " + jobId + "...", true);
        }
        continue;
      }
      var job = (detail.jobs || []).find(function (row) { return row.id === jobId; });
      if (!job) throw new Error("Scene job could not be found. Refresh the project to check its status.");
      if (job.status === "QUEUED" || job.status === "RUNNING") {
        if (activeProjectId === projectId) {
          showBanner("Nova is generating the scene in the background... " + String((attempt + 1) * 5) + "s", true);
        }
        continue;
      }
      var asset = (detail.assets || []).find(function (row) {
        return (job.result_asset_ids || []).indexOf(row.id) !== -1;
      });
      var provider = asset && asset.metadata && asset.metadata.provider_result;
      if (job.status === "ERROR" || job.status === "FAILED") {
        throw new Error(job.message || "Scene generation failed. Retry to resume the saved task.");
      }
      return { job: job, asset: asset, provider: provider || { status: job.status, message: job.message }, url: asset && asset.url };
    }
    throw new Error("Scene is still running. Refresh or click Generate Next AI Scene to reconnect to this job.");
  }

  async function waitForFinalPromo(projectId, queuedAt) {
    var startedMs = Date.parse(queuedAt || "") || Date.now();
    var attempts = 0;
    while (attempts < 48) {
      await new Promise(function (resolve) { setTimeout(resolve, 5000); });
      attempts += 1;
      var detail = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId));
      var assets = detail.assets || [];
      var fresh = assets.filter(function (row) {
        if (row.title !== "Final AMICOR Nova promo") return false;
        var createdMs = Date.parse(row.created_at || "") || 0;
        return createdMs >= startedMs - 2000;
      });
      var finished = fresh.slice().reverse().find(function (row) {
        return row.status === "GENERATED" && row.url && row.media_available !== false;
      });
      if (finished) return { status: "GENERATED", asset: finished };
      var failed = fresh.slice().reverse().find(function (row) {
        return row.status === "ERROR";
      });
      if (failed) {
        throw new Error(failed.content || "Final promo render failed.");
      }
      if (attempts % 2 === 0) {
        showBanner("Nova is rendering the final promo in the background... " + String(attempts * 5) + "s", true);
        await refreshAssets();
      }
    }
    throw new Error("Final promo is still rendering. Refresh this page in a minute to check the finished video.");
  }

  function renderPreflight(quote) {
    latestPreflight = quote || null;
    var el = $("preflight-status");
    var confirmBtn = $("confirm-budget");
    if (!el) return;
    if (!quote) {
      el.textContent = "Select a project, then run preflight.";
      if (confirmBtn) confirmBtn.disabled = true;
      return;
    }
    var balance = quote.balance || {};
    var balanceText = balance.status === "owner_reported"
      ? ("Owner-reported balance: $" + String(balance.amount))
      : "Balance: cannot verify (no automatic top-up)";
    var lines = [
      "Estimated total: $" + String(quote.estimated_total_usd) + " USD (planning only)",
      balanceText,
      "Paid render allowed by quote: " + (quote.paid_render_allowed ? "yes" : "no"),
      "Owner budget confirmed: " + (quote.owner_budget_confirmed ? "yes" : "no"),
      "Auto purchase/top-up: off"
    ];
    (quote.line_items || []).forEach(function (item) {
      lines.push("- " + item.label + ": $" + String(item.estimated_usd));
    });
    el.innerHTML = lines.map(function (line) { return "<div>" + escapeHtml(line) + "</div>"; }).join("");
    if (confirmBtn) {
      confirmBtn.disabled = !quote.paid_render_allowed || !!quote.owner_budget_confirmed;
    }
  }

  var runPreflightBtn = $("run-preflight");
  if (runPreflightBtn) {
    runPreflightBtn.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Select a project before running preflight.", false);
        return;
      }
      runPreflightBtn.disabled = true;
      var projectId = activeProjectId;
      var revision = activeProjectRevision;
      try {
        var quote = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/preflight");
        if (activeProjectId !== projectId || activeProjectRevision !== revision) return;
        renderPreflight(quote);
        showBanner("Preflight complete. No provider charges were made.", true);
      } catch (err) {
        if (activeProjectRevision === revision) showBanner(err.message || "Preflight failed.", false);
      } finally {
        runPreflightBtn.disabled = false;
      }
    });
  }
  var confirmBudgetBtn = $("confirm-budget");
  if (confirmBudgetBtn) {
    confirmBudgetBtn.addEventListener("click", async function () {
      if (!activeProjectId || !latestPreflight) {
        showBanner("Run preflight for the active project first.", false);
        return;
      }
      confirmBudgetBtn.disabled = true;
      var projectId = activeProjectId;
      var revision = activeProjectRevision;
      var quote = latestPreflight;
      try {
        var body = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/budget-confirm", {
          method: "POST",
          body: JSON.stringify({
            confirmed: true,
            acknowledged_estimate_usd: quote.estimated_total_usd,
            quote_fingerprint: quote.quote_fingerprint,
            note: "Owner confirmed preflight estimate before paid render."
          })
        });
        if (activeProjectId !== projectId || activeProjectRevision !== revision) return;
        renderPreflight(body.quote || quote);
        showBanner("Budget confirmation saved for this project. Still no automatic purchases.", true);
      } catch (err) {
        if (activeProjectId !== projectId || activeProjectRevision !== revision) return;
        showBanner(err.message || "Budget confirmation failed.", false);
        confirmBudgetBtn.disabled = false;
      }
    });
  }

  var latestStudioOrderId = null;

  async function runWalkingRender(endpoint, button, startMessage, successMessage) {
    button.disabled = true;
    try {
      // Never rely on a bare localStorage id — always resolve against the live project list.
      var projectId = await ensureSecondCommercialSelected();
      if (!projectId) {
        showBanner("No Studio project found. Sign in, then click Select Second Commercial (or create a 30s project).", false);
        return;
      }
      showBanner(startMessage + " Active: " + projectId, true);
      var rendered = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId) + endpoint, {
        method: "POST",
        body: JSON.stringify({})
      });
      var polled = rendered;
      if (rendered.job && rendered.job.id) {
        polled = await pollStudioJob(projectId, rendered.job.id);
      }
      renderOutput(polled || rendered);
      await refreshAssets();
      var status = polled && polled.job && polled.job.status;
      if (status === "ERROR") {
        showBanner("Render failed: " + (polled.job.message || "Unknown error."), false);
      } else {
        var complete = rendered && rendered.commercial_complete === true;
        showBanner(
          complete
            ? successMessage
            : (successMessage + " Commercial complete stays off until real motion, lip-sync, clean narration, and provider/license clearance."),
          true
        );
      }
    } catch (err) {
      showBanner(err.message || "Walking render failed.", false);
    } finally {
      button.disabled = false;
    }
  }

  var walkingPresenterButton = $("build-walking-presenter");
  if (walkingPresenterButton) {
    walkingPresenterButton.addEventListener("click", function () {
      runWalkingRender(
        "/assemble/walking-presenter-proof",
        walkingPresenterButton,
        "Rendering the 5–6s walking presenter proof. No paid provider is charged.",
        "Walking presenter proof ready. Download the MP4 from assets."
      );
    });
  }

  var walkingCommercialButton = $("build-walking-commercial-30s");
  if (walkingCommercialButton) {
    walkingCommercialButton.addEventListener("click", function () {
      return runWalkingRender(
        "/assemble/walking-commercial-30s",
        walkingCommercialButton,
        "Rendering the 30s walking talking commercial. No paid provider is charged.",
        "30s presenter pipeline is ready for owner review and download. This is separate from the title-card montage."
      );
    });
  }

  var acceptVoiceLicenseBtn = $("accept-voice-license");
  if (acceptVoiceLicenseBtn) {
    acceptVoiceLicenseBtn.addEventListener("click", async function () {
      acceptVoiceLicenseBtn.disabled = true;
      try {
        var projectId = await ensureSecondCommercialSelected();
        if (!projectId) {
          showBanner("No Studio project found. Sign in, then click Select Second Commercial.", false);
          return;
        }
        var body = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/voice-license", {
          method: "POST",
          body: JSON.stringify({
            accepted: true,
            note: "Owner accepts Studio neural voice for this commercial."
          })
        });
        renderOutput(body);
        showBanner("Voice license accepted on the active project. Future walking renders use license_status GREEN.", true);
      } catch (err) {
        showBanner(err.message || "Voice license acceptance failed.", false);
      } finally {
        acceptVoiceLicenseBtn.disabled = false;
      }
    });
  }

  var selectSecondCommercialBtn = $("select-second-commercial");
  if (selectSecondCommercialBtn) {
    selectSecondCommercialBtn.addEventListener("click", async function () {
      selectSecondCommercialBtn.disabled = true;
      try {
        var projectId = await ensureSecondCommercialSelected();
        if (!projectId) {
          showBanner("AMICOR Second Commercial was not found. Create a 30s promo project first.", false);
          return;
        }
        var match = findSecondCommercialProject(projectRowsCache);
        showBanner("Active project: " + ((match && match.title) || projectId) + ". Accept voice license, then Build 30s.", true);
      } catch (err) {
        showBanner(err.message || "Could not select Second Commercial.", false);
      } finally {
        selectSecondCommercialBtn.disabled = false;
      }
    });
  }

  function renderStudioPricing(pricing) {
    var el = $("studio-pricing");
    if (!el || !pricing) return;
    el.innerHTML =
      "<strong>$" + Number(pricing.customer_price_usd).toFixed(2) + "</strong> · " +
      escapeHtml(pricing.scope || "30-second commercial") +
      "<div class=\"muted\">Render ceiling $" + Number(pricing.internal_render_cost_ceiling_usd).toFixed(2) +
      " · " + escapeHtml(String(pricing.payment_mode || "unconfigured")) + " mode</div>";
  }

  function renderStudioOrders(payload) {
    var el = $("studio-orders");
    if (!el) return;
    var orders = (payload && payload.orders) || [];
    if (!orders.length) {
      el.textContent = "No Studio checkout orders yet for this project.";
      return;
    }
    el.innerHTML = orders.map(function (order) {
      var receipt = order.receipt ? (" · receipt " + escapeHtml(order.receipt.receipt_id || "ready")) : "";
      var cost = order.production_cost
        ? (" · est. render $" + Number(order.production_cost.estimated_render_cost_usd || 0).toFixed(2))
        : "";
      return "<div><strong>" + escapeHtml(order.id) + "</strong> · " +
        escapeHtml(String(order.status || "")) +
        " · job " + escapeHtml(String(order.job_status || "")) +
        " · $" + Number(order.customer_price_usd || 0).toFixed(2) +
        receipt + cost + "</div>";
    }).join("");
  }

  var loadPricingBtn = $("load-studio-pricing");
  if (loadPricingBtn) {
    loadPricingBtn.addEventListener("click", async function () {
      try {
        var pricing = await api("/api/nova/creative/pricing");
        renderStudioPricing(pricing);
        showBanner("AMICOR Studio pricing loaded. No charge was created.", true);
      } catch (err) {
        showBanner(err.message || "Could not load Studio pricing.", false);
      }
    });
  }

  var startCheckoutBtn = $("start-studio-checkout");
  if (startCheckoutBtn) {
    startCheckoutBtn.addEventListener("click", async function () {
      startCheckoutBtn.disabled = true;
      try {
        var projectId = await ensureSecondCommercialSelected();
        if (!projectId) {
          showBanner("No Studio project found. Sign in, then click Select Second Commercial before checkout.", false);
          return;
        }
        var started = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/checkout", {
          method: "POST",
          body: JSON.stringify({
            success_url: window.location.origin + "/nova/creative?checkout=success",
            cancel_url: window.location.origin + "/nova/creative?checkout=cancel"
          })
        });
        renderOutput(started);
        if (started.order) {
          latestStudioOrderId = started.order.id;
          renderStudioOrders({ orders: [started.order] });
        }
        var url = started.checkout && started.checkout.url;
        var mode = started.order && started.order.payment_mode;
        showBanner(
          "TEST checkout created for $" + Number((started.order || {}).customer_price_usd || 0).toFixed(2) +
            " (" + String(mode || "test") + "). " +
            (mode === "test" && url
              ? "Open the AMICOR Stripe Checkout link, or refresh orders after paying with a TEST card."
              : "Use Complete TEST payment to verify receipts without a live card."),
          true
        );
        if (mode === "test" && url && window.confirm("Open AMICOR Stripe TEST Checkout in a new tab?")) {
          window.open(url, "_blank", "noopener");
        }
      } catch (err) {
        showBanner(err.message || "Studio checkout failed.", false);
      } finally {
        startCheckoutBtn.disabled = false;
      }
    });
  }

  var completeTestCheckoutBtn = $("complete-studio-test-checkout");
  if (completeTestCheckoutBtn) {
    completeTestCheckoutBtn.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Select a project first.", false);
        return;
      }
      if (!latestStudioOrderId) {
        showBanner("Start a TEST checkout first, then complete it.", false);
        return;
      }
      completeTestCheckoutBtn.disabled = true;
      try {
        var body = await api(
          "/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) +
            "/checkout/orders/" + encodeURIComponent(latestStudioOrderId) + "/complete-test",
          { method: "POST", body: JSON.stringify({}) }
        );
        renderOutput(body);
        renderStudioOrders({ orders: body.order ? [body.order] : [] });
        showBanner("TEST payment recorded. Receipt and job status are ready.", true);
      } catch (err) {
        showBanner(err.message || "Could not complete TEST checkout.", false);
      } finally {
        completeTestCheckoutBtn.disabled = false;
      }
    });
  }

  var refreshOrdersBtn = $("refresh-studio-orders");
  if (refreshOrdersBtn) {
    refreshOrdersBtn.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Select a project first.", false);
        return;
      }
      try {
        var payload = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/checkout/orders");
        if (payload.pricing) renderStudioPricing(payload.pricing);
        renderStudioOrders(payload);
        if (payload.orders && payload.orders[0]) latestStudioOrderId = payload.orders[0].id;
        showBanner("Studio orders refreshed.", true);
      } catch (err) {
        showBanner(err.message || "Could not refresh Studio orders.", false);
      }
    });
  }

  var offlineMontageButton = $("build-offline-montage");
  if (offlineMontageButton) {
    offlineMontageButton.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Select a project with a storyboard first.", false);
        return;
      }
      offlineMontageButton.disabled = true;
      showBanner("Rendering the offline montage on this server. No paid provider is called.", true);
      try {
        var rendered = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/assemble/offline-commercial", {
          method: "POST"
        });
        var polled = rendered;
        if (rendered.job && rendered.job.id) {
          polled = await pollStudioJob(activeProjectId, rendered.job.id);
        }
        renderOutput(polled || rendered);
        var status = polled && polled.job && polled.job.status;
        await refreshAssets();
        if (status === "ERROR") {
          showBanner("Offline render failed: " + (polled.job.message || "Unknown error. Check the job result."), false);
        } else if (status === "GENERATED" || (polled && polled.ready === true)) {
          showBanner("Offline montage is PREVIEW_ONLY. Presenter was NOT USED. Download uses your signed-in session. Nothing was published.", true);
        } else {
          showBanner("Offline render is still processing or its final status was not confirmed. Refresh this project and check assets before attempting download.", false);
        }
      } catch (err) {
        showBanner(err.message || "Offline montage failed.", false);
      } finally {
        offlineMontageButton.disabled = false;
      }
    });
  }

  var novaLinksButton = $("prepare-nova-links");
  if (novaLinksButton) {
    novaLinksButton.addEventListener("click", async function () {
      var platformSelect = $("project-platform");
      var platform = platformSelect ? platformSelect.value : "TikTok";
      novaLinksButton.disabled = true;
      try {
        var pack;
        if (activeProjectId) {
          pack = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/click-destination?platform=" + encodeURIComponent(platform), {
            method: "POST"
          });
          await refreshAssets();
        } else {
          pack = await api("/api/nova/creative/click-destinations?platform=" + encodeURIComponent(platform) + "&verify=true");
        }
        renderOutput(pack);
        var clickReady = clickVerified(pack);
        var verified = clickReady ? "Verified first-party Nova URL." : "Not verified. Readiness stays orange.";
        showBanner("Profile Website field: " + pack.website_field_url + " " + verified + " Nothing was posted.", clickReady);
      } catch (err) {
        showBanner(err.message || "Could not prepare Nova links.", false);
      } finally {
        novaLinksButton.disabled = false;
      }
    });
  }

  var finalPromoButton = $("build-final-promo");
  if (finalPromoButton) {
    finalPromoButton.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Select the project you want to assemble first.", false);
        return;
      }
      var selectedProjectId = activeProjectId;
      finalPromoButton.disabled = true;
      showBanner("Starting final promo render in the background...", true);
      try {
        var started = await api("/api/nova/creative/projects/" + encodeURIComponent(selectedProjectId) + "/assemble/final-promo", {
          method: "POST"
        });
        renderOutput(started);
        showBanner(started.message || "Final promo render started.", true);
        var result = await waitForFinalPromo(selectedProjectId, started.queued_at);
        renderOutput(result);
        showBanner("Final AMICOR Nova promo created successfully. Scrolling to the finished video now.", true);
        await refreshAssets();
        var assetList = $("asset-list");
        if (assetList && assetList.scrollIntoView) {
          assetList.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      } catch (err) {
        var message = String((err && err.message) || "");
        var memoryBlocked = message.toLowerCase().indexOf("insufficient server memory headroom") >= 0 ||
          message.toLowerCase().indexOf("no encoder was started") >= 0;
        if (!memoryBlocked) {
          showBanner(message || "Final promo assembly failed.", false);
        } else {
          showBanner("Render server memory is tight, so Nova is switching to the browser-safe final promo builder...", true);
          try {
            var detail = await api("/api/nova/creative/projects/" + encodeURIComponent(selectedProjectId));
            var localResult = await buildFinalPromo(detail);
            var downloadLink = showFinalPromoDownload(localResult);
            var savedResult = null;
            try {
              savedResult = await uploadBrowserFinalPromo(selectedProjectId, localResult);
            } catch (saveErr) {
              showBanner("Final promo was built, but Nova could not save it to the project yet. Use the Download final promo link below. " + (saveErr.message || ""), false);
            }
            if (savedResult) await refreshAssets();
            if (downloadLink && downloadLink.scrollIntoView) {
              downloadLink.scrollIntoView({ behavior: "smooth", block: "center" });
            }
            if (savedResult) {
              showBanner(
                "Final promo built safely in this browser and saved to the project with " +
                String(localResult.clipCount || localResult.artworkCount || 0) +
                " visual asset(s)" + (localResult.hasVoice ? " and Nova voice." : "."),
                true
              );
            }
          } catch (fallbackErr) {
            showBanner(fallbackErr.message || "Browser-safe final promo build also failed.", false);
          }
        }
      } finally {
        finalPromoButton.disabled = false;
      }
    });
  }


  async function boot() {
    if (!token()) {
      setSignedIn(false);
      updateActiveProjectLabel();
      return;
    }
    try {
      // A locally cached token is not proof that the staging account survived a restart.
      // Confirm it with the server before showing the authenticated Studio controls.
      await api("/api/auth/me");
      setSignedIn(true);
      await refreshProviders();
      await refreshProjects();
      // Prefer the Second Commercial project so Build / Checkout never hit "select a project first".
      if (!activeProjectId || !projectRowsCache.some(function (row) { return row.id === activeProjectId; })) {
        await ensureSecondCommercialSelected();
      } else {
        updateActiveProjectLabel();
      }
      await refreshBrands();
      await refreshAssets();
    } catch (err) {
      showBanner(err.message, false);
    }
  }

  if (location.hostname === "nova-studio-validation-350.onrender.com") {
    $("staging-register-panel").style.display = "block";
    $("staging-register-toggle").addEventListener("click", function () {
      $("staging-register-form").classList.toggle("hidden");
    });
    $("staging-register-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      try {
        var email = $("staging-register-email").value.trim();
        var password = $("staging-register-password").value;
        if (password.length < 12) throw new Error("Test password must be at least 12 characters.");
        await api("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({ email: email, password: password, role: "staff", display_name: "Studio Tester" })
        });
        $("login-email").value = email;
        $("login-password").value = "";
        $("login-form").classList.remove("hidden");
        $("staging-register-form").classList.add("hidden");
        $("staging-register-password").value = "";
        showBanner("Test account created. Enter your NEW test password in the sign-in form. Never use your production password.", true);
      } catch (err) {
        showBanner("Test account creation failed: " + err.message, false);
      }
    });
  }
  $("sign-in-toggle").addEventListener("click", function () {
    $("login-form").classList.toggle("hidden");
  });
  $("sign-out").addEventListener("click", function () {
    setToken("");
    var shared = session();
    if (shared && typeof shared.clear === "function") shared.clear("creative_studio_signout");
    setActiveProjectId(null);
    setSignedIn(false);
    showBanner("Signed out.", true);
  });
  $("login-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      var body = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: $("login-email").value.trim(),
          password: $("login-password").value
        })
      });
      var shared = session();
      if (shared && typeof shared.start === "function") {
        shared.start({
          userId: body.user_id,
          email: body.email || $("login-email").value.trim(),
          name: body.name || body.display_name || $("login-email").value.trim(),
          role: body.role || body.session_role || "staff",
          organizationId: body.organization_id || null,
          organizationName: body.organization_name || null,
          accessToken: body.access_token || null,
          refreshToken: body.refresh_token || null,
          tokenExpiresAt: body.expires_in ? Date.now() + (Number(body.expires_in) * 1000) : null
        });
        if (typeof shared.applyAuthTokens === "function") shared.applyAuthTokens(body);
      }
      setToken(body.access_token || "");
      setSignedIn(true); // hide Sign in immediately; only Sign out while session is active
      showBanner("Signed in. Creative Studio session is ready.", true);
      boot();
    } catch (err) {
      showBanner(err.message, false);
    }
  });
  var amicorDefaults = {
    business_name: "AMICOR Nova",
    tagline: "AI help for everyday business operations",
    tone: "Professional, friendly, trustworthy",
    target_audience: "Small business owners, service businesses, local businesses, and growing teams",
    preferred_cta: "Visit getamicor.com to explore AMICOR Nova.",
    brand_description: "AMICOR Nova helps small businesses handle documents, emails, reports, scheduling, outreach, and other day-to-day operational tasks with AI-assisted drafts you review first. Save time, stay organized, and stay in control."
  };
  var latestPreflight = null;

  function applyAmicorBrandDefaults() {
    $("brand-name").value = amicorDefaults.business_name;
    $("brand-tagline").value = amicorDefaults.tagline;
    $("brand-tone").value = amicorDefaults.tone;
    $("brand-audience").value = amicorDefaults.target_audience;
    $("brand-cta").value = amicorDefaults.preferred_cta;
    $("brand-description").value = amicorDefaults.brand_description;
    showBanner("AMICOR Nova brand defaults loaded. Review them, then save the brand.", true);
  }

  var loadAmicorDefaults = $("load-amicor-brand-defaults");
  if (loadAmicorDefaults) {
    loadAmicorDefaults.addEventListener("click", applyAmicorBrandDefaults);
  }

  function applyProductionPreset(value) {
    var preset = String(value || "vertical_short");
    var platform = $("project-platform");
    var imageAspect = $("image-aspect");
    var presenterOutput = $("presenter-output-preset");
    var duration = $("project-duration");
    if (preset === "social_square") {
      if (platform) platform.value = "Instagram";
      if (imageAspect) imageAspect.value = "1:1";
      if (presenterOutput) presenterOutput.value = "1:1";
      if (duration) duration.value = "30";
    } else if (preset === "youtube_web") {
      if (platform) platform.value = "YouTube";
      if (imageAspect) imageAspect.value = "16:9";
      if (presenterOutput) presenterOutput.value = "16:9";
      if (duration) duration.value = "60";
    } else {
      if (platform) platform.value = "TikTok";
      if (imageAspect) imageAspect.value = "9:16";
      if (presenterOutput) presenterOutput.value = "9:16";
      if (duration) duration.value = "30";
    }
  }

  var productionPreset = $("production-preset");
  if (productionPreset) {
    productionPreset.addEventListener("change", function () {
      applyProductionPreset(productionPreset.value);
      showBanner("Production preset applied to platform, aspect ratio, presenter output, and duration.", true);
    });
    applyProductionPreset(productionPreset.value);
  }

  $("brand-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      var row = await api("/api/nova/creative/brands", {
        method: "POST",
        body: JSON.stringify({
          business_name: $("brand-name").value.trim(),
          tagline: $("brand-tagline").value.trim(),
          tone: $("brand-tone").value.trim(),
          target_audience: $("brand-audience").value.trim(),
          preferred_cta: $("brand-cta").value.trim(),
          brand_description: $("brand-description").value.trim()
        })
      });
      activeBrandId = row.id;
      if (!activeProjectId) {
        showBanner("Brand saved. Select a project before readiness can turn green.", true);
        await refreshBrands();
        return;
      }
      await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/brand", {
        method: "POST",
        body: JSON.stringify({ brand_id: row.id })
      });
      var persisted = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId));
      if (!persisted.brand || persisted.brand.id !== row.id) {
        throw new Error("Brand did not persist on this project.");
      }
      showBanner("Brand saved on this project.", true);
      await refreshBrands();
      await refreshAssets();
    } catch (err) {
      showBanner(err.message, false);
    }
  });
  $("project-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var titleInput = $("project-title");
    var createBtn = $("project-create-btn");
    var title = (titleInput.value || "").trim();
    if (!title) {
      showBanner("Project title is required.", false);
      titleInput.focus();
      return;
    }
    createBtn.disabled = true;
    try {
      var row = await api("/api/nova/creative/projects", {
        method: "POST",
        body: JSON.stringify({
          title: title,
          project_type: $("project-type").value,
          platform: $("project-platform").value,
          duration_target: Number($("project-duration").value),
          audience: $("project-audience").value.trim(),
          tone: $("project-tone").value.trim(),
          objective: $("project-objective").value.trim(),
          brand_profile_id: activeBrandId
        })
      });
      setActiveProjectId(row.id);
      showBanner("Project created", true);
      await refreshProjects();
      await refreshAssets();
    } catch (err) {
      showBanner(err.message || "Project create failed.", false);
    } finally {
      createBtn.disabled = false;
    }
  });
  var saveProjectSettings = $("project-save-settings");
  if (saveProjectSettings) {
    saveProjectSettings.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Select an active project first.", false);
        return;
      }
      saveProjectSettings.disabled = true;
      try {
        var payload = {
          title: ($("project-title").value || "").trim(),
          project_type: $("project-type").value,
          platform: $("project-platform").value,
          duration_target: Number($("project-duration").value),
          audience: $("project-audience").value.trim(),
          tone: $("project-tone").value.trim(),
          objective: $("project-objective").value.trim(),
          presenter_mode: $("presenter-mode").value,
          motion_style: $("presenter-motion-style").value,
          framing: $("presenter-framing").value,
          output_preset: $("presenter-output-preset").value,
          voice: $("presenter-voice").value,
          image_aspect: $("image-aspect").value,
          captions: true
        };
        var body = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId), {
          method: "PATCH",
          body: JSON.stringify(payload)
        });
        showBanner(body.message || "Active project settings saved.", true);
        await refreshProjects();
        await refreshAssets();
      } catch (err) {
        showBanner(err.message || "Could not save active project settings.", false);
      } finally {
        saveProjectSettings.disabled = false;
      }
    });
  }

  $("brief-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    if (!activeProjectId) {
      showBanner("Create or select a project first.", false);
      return;
    }
    try {
      var row = await api("/api/nova/creative/briefs", {
        method: "POST",
        body: JSON.stringify({
          project_id: activeProjectId,
          topic: $("brief-topic").value.trim(),
          cta: $("brief-cta").value.trim(),
          style: $("brief-style").value.trim(),
          platform: $("project-platform").value,
          audience: $("project-audience").value.trim(),
          tone: $("project-tone").value.trim(),
          duration_target: Number($("project-duration").value)
        })
      });
      showBanner("Brief saved.", true);
      renderOutput(row);
    } catch (err) {
      showBanner(err.message, false);
    }
  });
  function presenterPayload() {
    return {
      script: ($("presenter-script").value || "").trim(),
      voice: ($("presenter-voice") && $("presenter-voice").value) || "shimmer",
      captions: true,
      presenter_style: "warm professional small-business presenter",
      presenter_mode: ($("presenter-mode") && $("presenter-mode").value) || "full_body",
      motion_style: ($("presenter-motion-style") && $("presenter-motion-style").value) || "calm_professional",
      framing: ($("presenter-framing") && $("presenter-framing").value) || "full_frame",
      output_preset: ($("presenter-output-preset") && $("presenter-output-preset").value) || "9:16"
    };
  }

  async function runPresenterAction(kind, button) {
    if (!activeProjectId) {
      showBanner("Create or select a project first.", false);
      return;
    }
    if (presenterScriptProjectId !== activeProjectId) {
      showBanner("Wait for this project's saved script to load before continuing.", false);
      return;
    }
    var payload = presenterPayload();
    var projectId = activeProjectId;
    var revision = activeProjectRevision;
    if (!payload.script) {
      showBanner("Enter the presenter script first.", false);
      return;
    }
    var endpoint = kind === "save" ? "presenter/script" :
      (kind === "voice" ? "presenter/voice" : "presenter/preview");
    var messages = {
      save: ["Saving presenter script...", "Presenter script saved."],
      voice: ["Generating the presenter voice from this exact script...", "Presenter voice generated."],
      preview: ["Preparing presenter render...", "Presenter render prepared."]
    };
    button.disabled = true;
    showBanner(messages[kind][0], true);
    try {
      var body = await api("/api/nova/creative/projects/" + encodeURIComponent(projectId) + "/" + endpoint, {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (activeProjectId !== projectId || activeProjectRevision !== revision) return;
      renderOutput(body);
      var status = body && (body.status || (body.provider && body.provider.status));
      if (status === "CONFIG_REQUIRED") {
        showBanner(body.message || "Talking presenter provider must be connected before lip-synced preview generation.", false);
      } else {
        showBanner(body.message || messages[kind][1], true);
      }
      await refreshAssets();
    } catch (err) {
      if (activeProjectRevision === revision) showBanner(err.message || "Presenter action failed.", false);
    } finally {
      if (activeProjectRevision === revision) button.disabled = false;
    }
  }

  var presenterMode = $("presenter-mode");
  if (presenterMode) presenterMode.addEventListener("change", function () {
    var framing = $("presenter-framing");
    if (framing) framing.value = { head: "close_up", half_body: "waist_up", full_body: "full_frame" }[presenterMode.value];
  });

  ["save-presenter-script", "generate-presenter-voice", "preview-talking-presenter"].forEach(function (id) {
    var button = $(id);
    if (!button) return;
    button.addEventListener("click", function () {
      var kind = id === "save-presenter-script" ? "save" : (id === "generate-presenter-voice" ? "voice" : "preview");
      runPresenterAction(kind, button);
    });
  });

  document.querySelectorAll("[data-action]").forEach(function (button) {
    button.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Create or select a project first.", false);
        return;
      }
      var action = button.getAttribute("data-action");
      var labels = {
        script: { working: "Working: Generate Script...", ok: "Script generated." },
        caption: { working: "Working: Generate Caption...", ok: "Caption generated." },
        storyboard: { working: "Working: Generate Storyboard...", ok: "Storyboard generated." },
        "image-prompt": { working: "Working: Generate Image Prompt...", ok: "Image prompt generated." },
        image: { working: "Working: Generating image...", ok: "Image generated and added to this project." },
        video: { working: "Starting the next scene in the background. Progress will update automatically...", ok: "Scene video generation finished." },
        voice: { working: "Working: generating voice narration...", ok: "Voice narration generated." },
        export: { working: "Working: Export Project Package...", ok: "Project package exported." }
      };
      var meta = labels[action];
      if (!meta) {
        showBanner("Unknown generate action.", false);
        return;
      }
      var path = "/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/";
      var requestBody = null;
      if (action === "script") path += "generate/script";
      else if (action === "caption") path += "generate/caption";
      else if (action === "storyboard") path += "generate/storyboard";
      else if (action === "image-prompt") {
        path += "generate/image-prompt";
        requestBody = { aspect_ratio: $("image-aspect").value || "9:16" };
      } else if (action === "image") {
        path += "generate/image";
        requestBody = { aspect_ratio: $("image-aspect").value || "9:16" };
        var customImagePrompt = $("custom-image-prompt");
        if (customImagePrompt && customImagePrompt.value.trim()) requestBody.prompt = customImagePrompt.value.trim();
      } else if (action === "video") path += "generate/video";
      else if (action === "voice") path += "generate/voice";
      else if (action === "export") {
        path += "export";
        requestBody = { format: "markdown" };
      } else return;

      var selectedProjectId = activeProjectId;
      button.disabled = true;
      showBanner(meta.working, true);
      try {
        var options = { method: "POST" };
        if (requestBody) options.body = JSON.stringify(requestBody);
        var body = await api(path, options);
        if (action === "video" && body.status === "PROCESSING" && body.job) {
          body = await waitForScene(selectedProjectId, body.job.id);
        }
        renderOutput(body);
        var providerStatus = body && body.provider && body.provider.status;
        var providerMessage = body && body.provider && body.provider.message;
        if (providerStatus === "PROCESSING") {
          showBanner(providerMessage || "This storyboard scene is still processing. Click Generate Real AI Video again shortly.", true);
        } else if (body && body.provider && body.provider.all_scenes_generated) {
          showBanner("All storyboard scenes now have AI motion clips. Next step: build the final promo.", true);
        } else if ((action === "video" || action === "voice" || action === "image") &&
            providerStatus && providerStatus !== "GENERATED" && providerStatus !== "AVAILABLE") {
          showBanner(providerMessage || (action + " generation failed."), false);
        } else {
          showBanner(meta.ok, true);
        }
        await refreshAssets();
        await refreshProjects();
      } catch (err) {
        showBanner(err.message || ("Action failed: " + action), false);
      } finally {
        button.disabled = false;
      }
    });
  });

  boot();
})();


