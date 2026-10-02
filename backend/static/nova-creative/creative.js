(function () {
  var tokenKey = "amicor_nova_creative_token";
  var activeProjectKey = "amicor_nova_creative_active_project";
  var activeProjectId = localStorage.getItem(activeProjectKey) || null;
  var activeBrandId = null;

  function setActiveProjectId(value) {
    activeProjectId = value || null;
    if (activeProjectId) localStorage.setItem(activeProjectKey, activeProjectId);
    else localStorage.removeItem(activeProjectKey);
  }

  function $(id) { return document.getElementById(id); }
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

    if (!clips.length) {
      throw new Error("Generate at least one AI scene before building the final promo.");
    }

    var audioAssets = assets.filter(function (row) {
      return row.kind === "audio" && row.url && String(row.status || "").toUpperCase() === "GENERATED";
    });
    var voiceAsset = audioAssets.length ? audioAssets[audioAssets.length - 1] : null;

    var firstVideo = await loadVideo(clips[0].url);
    var logo = await loadImage("/static/branding/amicor-logo-full.png");
    var canvas = document.createElement("canvas");
    canvas.width = firstVideo.videoWidth || 720;
    canvas.height = firstVideo.videoHeight || 1280;
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

    recorder.start(250);
    if (audioElement) {
      audioElement.currentTime = 0;
      await audioElement.play();
    }

    for (var clipIndex = 0; clipIndex < clips.length; clipIndex += 1) {
      await playClip(clips[clipIndex], clipIndex === 0 ? firstVideo : null);
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
      fileName: "amicor-nova-final-promo.webm",
      clipCount: clips.length,
      hasVoice: Boolean(voiceAsset)
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
    meta.textContent = result.clipCount + " AI scene clip(s)" + (result.hasVoice ? " · Nova voice included" : " · no voice track");

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
    var headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    var res;
    try {
      var shared = (typeof window !== "undefined" && window.AmiCorSession) ? window.AmiCorSession : null;
      if (shared && typeof shared.ensureReady === "function") {
        await shared.ensureReady();
      }
      if (shared && typeof shared.authFetch === "function") {
        res = await shared.authFetch(path, Object.assign({}, options, { headers: headers }));
      } else {
        if (typeof token === "function" && token()) headers.Authorization = "Bearer " + token();
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
      if (typeof setToken === "function") setToken("");
      if (typeof setSignedIn === "function") setSignedIn(false);
      if (typeof $ === "function" && $("login-form")) $("login-form").classList.remove("hidden");
      throw new Error("Session expired. Sign in again. (401) Your active Creative Studio project is preserved.");
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
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
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
  }
  async function refreshProjects() {
    var body = await api("/api/nova/creative/projects");
    var rows = body.projects || [];
    if (activeProjectId && !rows.some(function (row) { return row.id === activeProjectId; })) {
      setActiveProjectId(null);
    }
    $("project-list").innerHTML = rows.map(function (row) {
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
  async function refreshBrands() {
    var body = await api("/api/nova/creative/brands");
    $("brand-list").innerHTML = (body.brands || []).map(function (row) {
      return "<div class=\"item\" data-id=\"" + escapeHtml(row.id) + "\"><strong>" + escapeHtml(row.business_name) + "</strong>" +
        "<div class=\"muted\">" + escapeHtml(row.tagline || row.tone || "") + "</div></div>";
    }).join("") || "<p class=\"hint\">No brands yet.</p>";
    Array.prototype.forEach.call(document.querySelectorAll("#brand-list .item"), function (el) {
      el.addEventListener("click", function () {
        activeBrandId = el.getAttribute("data-id");
        showBanner("Brand selected for new projects: " + activeBrandId, true);
      });
    });
  }
  async function refreshAssets() {
    if (!activeProjectId) {
      $("asset-list").innerHTML = "<p class=\"hint\">Select a project.</p>";
      return;
    }
    var detail = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId));
    $("asset-list").innerHTML = (detail.assets || []).map(function (row) {
      var media = "";
      var mediaAvailable = row.media_available !== false;
      if (row.kind === "image" && row.url && mediaAvailable) {
        var isAmicor = String(row.content || "").toUpperCase().indexOf("AMICOR") >= 0;
        media = "<figure class=\"generated-media\"><img src=\"" + escapeHtml(row.url) + "\" alt=\"" +
          escapeHtml(row.title || "Nova generated image") + "\" loading=\"lazy\" />" +
          (isAmicor ? "<img class=\"official-brand-overlay\" src=\"/static/branding/amicor-logo-full.png\" alt=\"AMICOR official logo\" />" : "") +
          "</figure>" +
          (isAmicor ? "<button type=\"button\" class=\"secondary branded-download\" data-image-url=\"" +
            escapeHtml(row.url) + "\" data-file-stem=\"" + escapeHtml((row.title || "amicor-nova").replace(/[^A-Za-z0-9_-]+/g, "-")) +
            "\">Download branded PNG</button> <button type=\"button\" class=\"secondary promo-video\" data-image-url=\"" +
            escapeHtml(row.url) + "\" data-file-stem=\"" + escapeHtml((row.title || "amicor-nova").replace(/[^A-Za-z0-9_-]+/g, "-")) +
            "\">Create 8s branded video</button>" : "");
      } else if (row.kind === "video" && row.url && mediaAvailable) {
        media = "<figure class=\"generated-media\"><video controls playsinline preload=\"metadata\" src=\"" +
          escapeHtml(row.url) + "\"></video></figure><a class=\"button secondary\" href=\"" +
          escapeHtml(row.url) + "\" download>Download AI video</a>";
      } else if (row.kind === "audio" && row.url && mediaAvailable) {
        media = "<div class=\"generated-media\"><audio controls preload=\"metadata\" src=\"" +
          escapeHtml(row.url) + "\"></audio></div><a class=\"button secondary\" href=\"" +
          escapeHtml(row.url) + "\" download>Download voice</a>";
      }
      return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong>" +
        "<span class=\"badge\">" + escapeHtml(row.status) + "</span>" +
        "<div class=\"muted\">" + escapeHtml(row.kind) + (row.url ? (mediaAvailable ? " · media ready" : " · media missing — regenerate") : " · no media URL") + "</div>" +
        media +
        "<div>" + escapeHtml(String(row.content || "").slice(0, 280)) + "</div></div>";
    }).join("") || "<p class=\"hint\">No assets yet.</p>";
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
  var resetMedia = $("reset-project-media");
  if (resetMedia) {
    resetMedia.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Select the project you want to reset first.", false);
        return;
      }
      if (!window.confirm("Reset all generated media for the active project? Script, captions, storyboard, and brief will be preserved.")) {
        return;
      }
      resetMedia.disabled = true;
      showBanner("Working: removing old media clutter from the active project...", true);
      try {
        var result = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/assets/reset-media", {
          method: "POST"
        });
        showBanner(
          "Media reset complete. Removed " + String(result.deleted_asset_records || 0) +
          " old media record(s). Script, captions, storyboard, and brief were preserved.",
          true
        );
        await refreshAssets();
      } catch (err) {
        showBanner(err.message || "Could not reset active project media.", false);
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
        showBanner(err.message || "Final promo assembly failed.", false);
      } finally {
        finalPromoButton.disabled = false;
      }
    });
  }


  async function boot() {
    if (!token()) {
      setSignedIn(false);
      return;
    }
    setSignedIn(true);
    try {
      await refreshProviders();
      await refreshProjects();
      await refreshBrands();
      await refreshAssets();
    } catch (err) {
      showBanner(err.message, false);
    }
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
      showBanner("Signed in. Creative Studio session is ready.", true);
      boot();
    } catch (err) {
      showBanner(err.message, false);
    }
  });
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
      showBanner("Brand saved.", true);
      refreshBrands();
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
      presenter_style: "warm professional small-business presenter"
    };
  }

  async function runPresenterAction(kind, button) {
    if (!activeProjectId) {
      showBanner("Create or select a project first.", false);
      return;
    }
    var payload = presenterPayload();
    if (!payload.script) {
      showBanner("Enter the presenter script first.", false);
      return;
    }
    var endpoint = kind === "save" ? "presenter/script" :
      (kind === "voice" ? "presenter/voice" : "presenter/preview");
    var messages = {
      save: ["Saving presenter script...", "Presenter script saved."],
      voice: ["Generating the presenter voice from this exact script...", "Presenter voice generated."],
      preview: ["Preparing talking presenter preview...", "Talking presenter preview prepared."]
    };
    button.disabled = true;
    showBanner(messages[kind][0], true);
    try {
      var body = await api("/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/" + endpoint, {
        method: "POST",
        body: JSON.stringify(payload)
      });
      renderOutput(body);
      var status = body && (body.status || (body.provider && body.provider.status));
      if (status === "CONFIG_REQUIRED") {
        showBanner(body.message || "Talking presenter provider must be connected before lip-synced preview generation.", false);
      } else {
        showBanner(body.message || messages[kind][1], true);
      }
      await refreshAssets();
    } catch (err) {
      showBanner(err.message || "Presenter action failed.", false);
    } finally {
      button.disabled = false;
    }
  }

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
