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
  function moneyText(amount, currency) {
    if (typeof amount !== "number") return "Unavailable";
    var code = currency ? String(currency) : "";
    return amount.toFixed(2) + (code ? " " + code : "");
  }
  function renderBuckets(buckets) {
    if (!buckets || !buckets.length) return "<p class=\"hint\">Unavailable</p>";
    return "<div class=\"bucket-grid\">" + buckets.map(function (bucket) {
      return "<article class=\"bucket-card\"><h4>" + escapeHtml(bucket.label || "") + "</h4>" +
        "<p class=\"value\">" + escapeHtml(moneyText(bucket.amount, "")) + "</p>" +
        "<p class=\"hint\">" + escapeHtml(String(bucket.count || 0)) + " records</p></article>";
    }).join("") + "</div>";
  }
  function renderSlice(slice) {
    var currency = slice.currency ? slice.currency : "Currency not recorded";
    var oldest = slice.oldest_age_days == null ? "Unavailable" : String(slice.oldest_age_days) + " days";
    return "<div class=\"currency-block\">" +
      "<h4>" + escapeHtml(currency) + " · Stripe TEST</h4>" +
      "<div class=\"aging-meta\">" +
      "<p>Total pending records<br><strong>" + escapeHtml(String(slice.count || 0)) + "</strong></p>" +
      "<p>Total pending amount<br><strong>" + escapeHtml(moneyText(slice.amount, slice.currency)) + "</strong></p>" +
      "<p>Oldest pending age<br><strong>" + escapeHtml(oldest) + "</strong></p>" +
      "</div>" +
      renderBuckets(slice.buckets) +
      "</div>";
  }
  function renderGroup(group) {
    if (!group || group.status === "unavailable") {
      return "<article class=\"aging-group\"><h3>" + escapeHtml((group && group.label) || "Group") +
        "</h3><p class=\"state unavailable\">Unavailable</p></article>";
    }
    var slices = (group.currencies || []).map(renderSlice).join("");
    if (!slices) slices = "<p class=\"hint\">No pending records in this group.</p>";
    return "<article class=\"aging-group\" data-group-key=\"" + escapeHtml(group.key || "") + "\">" +
      "<h3>" + escapeHtml(group.label || "Group") + "</h3>" +
      "<p class=\"state pending\">" + escapeHtml(group.measurement || "Age since created") + "</p>" +
      "<p class=\"source-note\">" + escapeHtml(group.source_note || "") + "</p>" +
      slices +
      "</article>";
  }
  function renderSection(hostId, section) {
    var host = $(hostId);
    if (!host) return;
    if (!section || section.status === "unavailable") {
      host.innerHTML = "<p class=\"state unavailable\">Unavailable</p>";
      return;
    }
    host.innerHTML = (section.groups || []).map(renderGroup).join("") || "<p class=\"state unavailable\">Unavailable</p>";
  }
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
    $("login-form").classList.add("hidden");
    var ident = identity();
    $("session-meta").textContent = on
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · Stripe TEST · read-only"
      : "Sign in to load aging totals.";
  }
  async function refresh() {
    if (!token()) {
      setSignedIn(false);
      return;
    }
    var aging = await api("/api/nova/accounting/aging");
    setSignedIn(true);
    $("as-of").textContent = aging.calculated_as_of_utc
      ? "Calculated as of " + aging.calculated_as_of_utc + " UTC"
      : "Calculated as of Unavailable";
    try {
      renderSection("customer-box", aging.customer_payment_pipeline);
      renderSection("freight-box", aging.freight_invoice_pipeline);
    } catch (_) {
      renderSection("customer-box", { status: "unavailable" });
      renderSection("freight-box", { status: "unavailable" });
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
      showBanner("Signed in. Aging totals are read-only.", true);
    }).catch(function (err) {
      showBanner(err.message || String(err));
    });
  });
  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message || String(err)); });
})();
