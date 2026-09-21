(function () {
  var tokenKey = "amicor_nova_creative_token";
  var activeProjectId = null;
  var activeBrandId = null;

  function $(id) { return document.getElementById(id); }
  function token() { return localStorage.getItem(tokenKey) || ""; }
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
    if (token()) headers.Authorization = "Bearer " + token();
    var res;
    try {
      res = await fetch(path, Object.assign({}, options, { headers: headers }));
    } catch (err) {
      throw new Error("Network error. Check your connection and try again.");
    }
    var body = null;
    try { body = await res.json(); } catch (err) { body = null; }
    if (res.status === 401) throw new Error("Session expired. Sign in again. (401)");
    if (res.status === 403) throw new Error("Access denied. (403)");
    if (res.status === 422) throw new Error(detailText(body, "Validation failed. (422)"));
    if (res.status >= 500) throw new Error("Temporary system error. (500)");
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
    $("project-list").innerHTML = (body.projects || []).map(function (row) {
      var active = row.id === activeProjectId ? " · ACTIVE" : "";
      return "<div class=\"item\" data-id=\"" + escapeHtml(row.id) + "\"><strong>" + escapeHtml(row.title) + "</strong>" +
        "<span class=\"badge\">" + escapeHtml(row.status) + "</span>" + active +
        "<div class=\"muted\">" + escapeHtml(row.project_type) + " · " + escapeHtml(row.platform) + "</div></div>";
    }).join("") || "<p class=\"hint\">No projects yet.</p>";
    Array.prototype.forEach.call(document.querySelectorAll("#project-list .item"), function (el) {
      el.addEventListener("click", function () {
        activeProjectId = el.getAttribute("data-id");
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
      return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong>" +
        "<span class=\"badge\">" + escapeHtml(row.status) + "</span>" +
        "<div class=\"muted\">" + escapeHtml(row.kind) + (row.url ? " · URL present" : " · no media URL") + "</div>" +
        "<div>" + escapeHtml(String(row.content || "").slice(0, 280)) + "</div></div>";
    }).join("") || "<p class=\"hint\">No assets yet.</p>";
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
    activeProjectId = null;
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
      setToken(body.access_token);
      showBanner("Signed in.", true);
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
      activeProjectId = row.id;
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
  document.querySelectorAll("[data-action]").forEach(function (button) {
    button.addEventListener("click", async function () {
      if (!activeProjectId) {
        showBanner("Create or select a project first.", false);
        return;
      }
      var action = button.getAttribute("data-action");
      var path = "/api/nova/creative/projects/" + encodeURIComponent(activeProjectId) + "/";
      if (action === "script") path += "generate/script";
      else if (action === "caption") path += "generate/caption";
      else if (action === "storyboard") path += "generate/storyboard";
      else if (action === "image-prompt") path += "generate/image-prompt";
      else if (action === "image") path += "generate/image";
      else if (action === "video") path += "generate/video";
      else if (action === "voice") path += "generate/voice";
      else if (action === "export") path += "export";
      else return;
      try {
        var body = await api(path, {
          method: "POST",
          body: JSON.stringify(action === "export" ? { format: "markdown" } : { aspect_ratio: "9:16" })
        });
        renderOutput(body);
        showBanner((body.job && body.job.status) || (body.export && body.export.status) || "Done", true);
        refreshAssets();
        refreshProjects();
      } catch (err) {
        showBanner(err.message, false);
      }
    });
  });

  boot();
})();
