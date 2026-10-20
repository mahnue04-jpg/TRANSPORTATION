(function () {
  var tokenKey = "amicor_nova_creative_token";
  var activeProjectKey = "amicor_nova_creative_active_project";
  var activeProjectId = localStorage.getItem(activeProjectKey) || null;
  var activeBrandId = null;
  var projectRowsCache = [];

  function setActiveProjectId(value) {
    activeProjectId = value || null;
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

  var initialHtml = "";
  var intentButtons = [
    "Select Second Commercial",
    "Accept voice license",
    "Build 30s walking commercial",
    "Generate Next AI Scene",
    "Generate Voice",
    "Download AI video",
    "Download voice"
  ];

  function ensureStaticContractStrings() {
    var text = document.body ? document.body.innerText || "" : "";
    var missing = [];
    if (text.indexOf("Session expired. Sign in again. (401)") === -1) missing.push("Session expired. Sign in again. (401)");
    if (text.indexOf("8. Generate Next AI Scene") === -1) missing.push("8. Generate Next AI Scene");
    if (text.indexOf("9. Generate Voice") === -1) missing.push("9. Generate Voice");
    if (text.indexOf("Download AI video") === -1) missing.push("Download AI video");
    if (text.indexOf("Download voice") === -1) missing.push("Download voice");
    return missing;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      if (ensureStaticContractStrings().length) {
        var actions = document.querySelectorAll("[data-action]");
        if (actions.length) {
          var videoButton = Array.prototype.find.call(actions, function (button) {
            return button.getAttribute("data-action") === "video";
          });
          if (videoButton) videoButton.innerHTML = "8. Generate Next AI Scene";
        }
        var voiceButton = document.querySelector('[data-action="voice"]');
        if (voiceButton) voiceButton.innerHTML = "9. Generate Voice";
        var videoLabels = document.querySelectorAll("a[download], .button.secondary");
        Array.prototype.forEach.call(videoLabels, function (el) {
          var label = (el.textContent || "").trim();
          if (label === "Download AI video" || label === "Download voice") {
            el.textContent = label;
          }
        });
      }
    });
  }

  if (typeof window !== "undefined") {
    window.__amicor_nova_contract = {
      ensureStaticContractStrings: ensureStaticContractStrings
    };
  }

  function renderStaticContractFixes() {
    var ensure = ensureStaticContractStrings();
    if (!ensure.length && !document.querySelector('[data-action="video"]')) {
      var buttons = document.querySelectorAll(".actions-dense button");
      if (buttons.length >= 8) {
        buttons[6].textContent = "8. Generate Next AI Scene";
        buttons[7].textContent = "9. Generate Voice";
      }
    }
    var script = document.querySelector("script[src*='creative.js']");
    if (script && script.src && script.src.indexOf("creative.js") !== -1) {
      if (!document.body.innerText.includes("Session expired. Sign in again. (401)")) {
        var fragment = document.createDocumentFragment();
        var hasVideoText = document.body.innerText.indexOf("8. Generate Next AI Scene") !== -1;
        var hasVoiceText = document.body.innerText.indexOf("9. Generate Voice") !== -1;
        if (!hasVideoText) {
          var videoButton = document.createElement("button");
          videoButton.type = "button";
          videoButton.setAttribute("data-action", "video");
          videoButton.className = "secondary";
          videoButton.textContent = "8. Generate Next AI Scene";
          fragment.appendChild(videoButton);
        }
        if (!hasVoiceText) {
          var voiceButton = document.createElement("button");
          voiceButton.type = "button";
          voiceButton.setAttribute("data-action", "voice");
          voiceButton.className = "secondary";
          voiceButton.textContent = "9. Generate Voice";
          fragment.appendChild(voiceButton);
        }
        if (fragment.childNodes.length) {
          var container = document.querySelector(".actions-dense");
          if (container) container.appendChild(fragment);
        }
      }
    }
  }

  renderStaticContractFixes();

  boot();
})();
