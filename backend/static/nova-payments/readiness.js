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
  function statusClass(status) {
    return String(status || "not-verified").toLowerCase().replace(/\s+/g, "-");
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
  function renderChecks(section) {
    var host = $("section-" + (section && section.key ? section.key : ""));
    if (!host) return;
    var checks = (section && section.checks) || [];
    if (!checks.length) {
      host.innerHTML = "<p class=\"hint\">Unavailable</p>";
      return;
    }
    host.innerHTML = checks.map(function (row) {
      var status = row.status || "Not verified";
      var extra = row.classification ? " · " + row.classification : "";
      return "<article class=\"check-card\" data-check-key=\"" + escapeHtml(row.key || "") + "\">" +
        "<h3>" + escapeHtml(row.label || "Check") + "</h3>" +
        "<p class=\"state " + escapeHtml(statusClass(status)) + "\">" + escapeHtml(status) + extra + "</p>" +
        "<p>" + escapeHtml(row.explanation || "") + "</p>" +
        "<p class=\"hint\">" + escapeHtml(row.evidence_source || "") + "</p>" +
        "</article>";
    }).join("");
  }
  function renderBlockers(blockers) {
    var host = $("blocker-list");
    if (!host) return;
    if (!blockers || !blockers.length) {
      host.innerHTML = "<li>No blockers were returned. LIVE readiness is still not independently verified.</li>";
      return;
    }
    host.innerHTML = blockers.map(function (row) {
      return "<li><strong>" + escapeHtml(row.area || "Area") + "</strong> — " +
        escapeHtml(row.current_status || "Not verified") +
        "<span class=\"meta\">" + escapeHtml(row.why_blocks_live || "") + "</span>" +
        "<span class=\"meta\">" + escapeHtml(row.required_action || "") + "</span>" +
        "<span class=\"meta\">Authorized now: " + (row.action_authorized_now ? "Yes" : "Not authorized") + "</span>" +
        "<span class=\"meta\">" + escapeHtml(row.evidence_source || "") + "</span></li>";
    }).join("");
  }
  function renderSummary(payload) {
    var mode = (payload && payload.stripe_mode) || "Not verified";
    $("mode-box").textContent = "Current classified mode: " + mode +
      ". Configured is not verified. TEST is not LIVE. A single go-ahead is not shown because LIVE customer payments and driver payouts are not independently verified.";
    (payload.sections || []).forEach(renderChecks);
    renderBlockers(payload.blockers || []);
  }
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
    $("login-form").classList.add("hidden");
    var ident = identity();
    $("session-meta").textContent = on
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · read-only · no setup controls"
      : "Sign in with an admin account to load readiness details.";
  }
  async function refresh() {
    if (!token()) {
      setSignedIn(false);
      return;
    }
    var payload = await api("/api/nova/payments/readiness");
    setSignedIn(true);
    try {
      renderSummary(payload);
    } catch (_) {
      showBanner("Readiness details could not be rendered. Saved work was not changed.");
    }
    try {
      var verified = await api("/api/nova/payments/readiness/verify");
      renderSummary(verified);
    } catch (_) {
      /* Cached or classified statuses remain. No Stripe write is attempted. */
    }
  }
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
      showBanner("Signed in. Payments readiness is read-only.", true);
    }).catch(function (err) {
      showBanner(err.message || String(err));
    });
  });
  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message || String(err)); });
})();
