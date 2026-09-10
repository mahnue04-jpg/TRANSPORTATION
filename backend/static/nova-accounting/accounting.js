"use strict";

(function () {
  function $(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function identity() {
    var current = session() && session().getCurrent ? session().getCurrent() : null;
    return current && current.identity ? current.identity : null;
  }
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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
  async function api(path, options) {
    var headers = { "Content-Type": "application/json" };
    if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
    else if (token()) headers.Authorization = "Bearer " + token();
    var response;
    try {
      response = await fetch(path, Object.assign({}, options || {}, { headers: headers }));
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
  function moneyText(amount) {
    if (typeof amount !== "number") return "Unavailable";
    return "$" + amount.toFixed(2);
  }
  var currentWindow = "all";
  function renderMetrics(metrics) {
    var host = $("metrics-box");
    if (!host) return;
    if (!metrics || !metrics.length) {
      host.innerHTML = "<p class=\"hint\">Unavailable</p>";
      return;
    }
    host.innerHTML = metrics.map(function (row) {
      var unavailable = !row || row.status === "unavailable" || row.amount_usd == null;
      var state = unavailable ? "unavailable" : (row.state || "unavailable");
      var value = unavailable ? "Unavailable" : moneyText(row.amount_usd);
      var windowLabel = row.window_label || "All time";
      var sourceNote = row.source_note || "";
      return "<article class=\"metric-card\" data-metric-key=\"" + escapeHtml(row.key || "") + "\">" +
        "<h3>" + escapeHtml(row.label || "Metric") + "</h3>" +
        "<p class=\"state " + escapeHtml(state) + "\">" + escapeHtml(state) + "</p>" +
        "<p class=\"window-label\">" + escapeHtml(windowLabel) + "</p>" +
        "<p class=\"source-note\">" + escapeHtml(sourceNote) + "</p>" +
        "<p class=\"value\">" + escapeHtml(value) + "</p>" +
        "<p class=\"definition\">" + escapeHtml(row.definition || "") + "</p>" +
        "</article>";
    }).join("");
  }
  function setWindowButtons() {
    document.querySelectorAll(".window-btn").forEach(function (btn) {
      btn.setAttribute("aria-pressed", btn.getAttribute("data-window") === currentWindow ? "true" : "false");
    });
  }
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
    $("login-form").classList.add("hidden");
    var ident = identity();
    $("session-meta").textContent = on
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · Stripe TEST · read-only"
      : "Sign in to load accounting totals.";
  }
  async function refresh() {
    if (!token()) {
      setSignedIn(false);
      return;
    }
    var summary = await api("/api/nova/accounting/summary?window=" + encodeURIComponent(currentWindow));
    setSignedIn(true);
    try {
      renderMetrics(summary.metrics);
    } catch (_) {
      renderMetrics([]);
    }
  }
  document.querySelectorAll(".window-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      currentWindow = btn.getAttribute("data-window") || "all";
      setWindowButtons();
      refresh().catch(function (err) { showBanner(err.message || String(err)); });
    });
  });
  $("sign-in-toggle").addEventListener("click", function () {
    $("login-form").classList.toggle("hidden");
  });
  $("sign-out").addEventListener("click", function () {
    if (session() && session().logout) session().logout();
    setSignedIn(false);
    showBanner("Signed out.", true);
  });
  $("login-form").addEventListener("submit", function (event) {
    event.preventDefault();
    api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: $("login-email").value.trim(),
        password: $("login-password").value
      })
    }).then(function (payload) {
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
      return refresh();
    }).then(function () {
      showBanner("Signed in. Accounting totals are read-only.", true);
    }).catch(function (err) {
      showBanner(err.message || String(err));
    });
  });
  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message || String(err)); });
})();
