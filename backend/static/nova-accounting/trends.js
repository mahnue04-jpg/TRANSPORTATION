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
    return amount.toFixed(2) + (currency ? " " + currency : "");
  }
  var currentMonths = "12";
  function barChart(months, currency) {
    if (!months || !months.length) return "<p class=\"hint\">Unavailable</p>";
    var max = 0;
    months.forEach(function (row) {
      if (typeof row.amount === "number" && row.amount > max) max = row.amount;
    });
    if (max <= 0) max = 1;
    var width = Math.max(320, months.length * 46);
    var height = 180;
    var plotLeft = 8;
    var plotBottom = 42;
    var plotTop = 22;
    var plotHeight = height - plotTop - plotBottom;
    var gap = 8;
    var barWidth = Math.max(12, (width - 16) / months.length - gap);
    var bars = months.map(function (row, index) {
      var value = typeof row.amount === "number" ? row.amount : 0;
      var barHeight = Math.round((value / max) * plotHeight);
      var x = plotLeft + index * (barWidth + gap);
      var y = plotTop + (plotHeight - barHeight);
      var title = (row.label || row.month) + ": " + moneyText(row.amount, currency) + ", " + (row.count || 0) + " records";
      return "<g>" +
        "<title>" + escapeHtml(title) + "</title>" +
        "<rect x=\"" + x + "\" y=\"" + y + "\" width=\"" + barWidth + "\" height=\"" + Math.max(barHeight, 1) + "\" fill=\"#3b9bff\" stroke=\"#eef6ff\"></rect>" +
        "<text x=\"" + (x + barWidth / 2) + "\" y=\"" + (height - 18) + "\" text-anchor=\"middle\" fill=\"#9db6ce\" font-size=\"10\">" + escapeHtml((row.month || "").slice(5)) + "</text>" +
        "<text x=\"" + (x + barWidth / 2) + "\" y=\"" + Math.max(12, y - 4) + "\" text-anchor=\"middle\" fill=\"#eef6ff\" font-size=\"9\">" + escapeHtml(typeof row.amount === "number" ? row.amount.toFixed(0) : "n/a") + "</text>" +
        "</g>";
    }).join("");
    return "<div class=\"trend-chart\"><svg role=\"img\" aria-label=\"Monthly amounts for " + escapeHtml(currency || "currency") + "\" viewBox=\"0 0 " + width + " " + height + "\">" + bars + "</svg></div>";
  }
  function tableFor(months, currency) {
    if (!months || !months.length) return "<p class=\"hint\">Unavailable</p>";
    var rows = months.map(function (row) {
      return "<tr><th scope=\"row\">" + escapeHtml(row.label || row.month) + "</th><td>" +
        escapeHtml(moneyText(row.amount, currency)) + "</td><td>" + escapeHtml(String(row.count || 0)) + "</td></tr>";
    }).join("");
    return "<table class=\"trend-table\"><caption>Same values as the chart</caption><thead><tr><th>Month</th><th>Amount</th><th>Records</th></tr></thead><tbody>" + rows + "</tbody></table>";
  }
  function renderSlice(slice) {
    var currency = slice.currency || "Currency not recorded";
    return "<div class=\"currency-block\">" +
      "<h4>" + escapeHtml(currency) + " · Stripe TEST</h4>" +
      "<p class=\"hint\">Excluded missing timestamps: " + escapeHtml(String(slice.excluded_missing_timestamp_count || 0)) + "</p>" +
      barChart(slice.months, slice.currency) +
      tableFor(slice.months, slice.currency) +
      "</div>";
  }
  function renderGroup(group) {
    if (!group || group.status === "unavailable") {
      return "<article class=\"aging-group\"><h3>" + escapeHtml((group && group.label) || "Group") + "</h3><p class=\"state unavailable\">Unavailable</p></article>";
    }
    var slices = (group.currencies || []).map(renderSlice).join("");
    var collectible = group.collectible === false && (group.key || "").indexOf("draft") !== -1 ? "<p class=\"hint\">Not collectible</p>" : "";
    return "<article class=\"aging-group\" data-group-key=\"" + escapeHtml(group.key || "") + "\">" +
      "<h3>" + escapeHtml(group.label || "Group") + "</h3>" +
      "<p class=\"state " + escapeHtml(group.state || "") + "\">" + escapeHtml(group.state || "") + "</p>" +
      collectible +
      "<p class=\"source-note\">" + escapeHtml(group.source_note || "") + "</p>" +
      slices +
      "</article>";
  }
  function renderStreams(streams) {
    var host = $("streams-box");
    if (!host) return;
    if (!streams || !streams.length) {
      host.innerHTML = "<p class=\"state unavailable\">Unavailable</p>";
      return;
    }
    host.innerHTML = streams.map(function (stream) {
      if (!stream || stream.status === "unavailable") {
        return "<section class=\"trend-stream\"><h2>" + escapeHtml((stream && stream.label) || "Stream") + "</h2><p class=\"state unavailable\">Unavailable</p></section>";
      }
      return "<section class=\"trend-stream\" data-stream-key=\"" + escapeHtml(stream.key || "") + "\"><h2>" +
        escapeHtml(stream.label || "Stream") + "</h2>" + (stream.groups || []).map(renderGroup).join("") + "</section>";
    }).join("");
  }
  function setMonthButtons() {
    document.querySelectorAll(".window-btn").forEach(function (btn) {
      btn.setAttribute("aria-pressed", btn.getAttribute("data-months") === currentMonths ? "true" : "false");
    });
  }
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
    $("login-form").classList.add("hidden");
    var ident = identity();
    $("session-meta").textContent = on
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · Stripe TEST · read-only"
      : "Sign in to load monthly trends.";
  }
  async function refresh() {
    if (!token()) {
      setSignedIn(false);
      return;
    }
    var payload = await api("/api/nova/accounting/trends?months=" + encodeURIComponent(currentMonths));
    setSignedIn(true);
    $("as-of").textContent = payload.calculated_as_of_utc
      ? "Calculated as of " + payload.calculated_as_of_utc + " UTC"
      : "Calculated as of Unavailable";
    renderStreams(payload.streams);
  }
  document.querySelectorAll(".window-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      currentMonths = btn.getAttribute("data-months") || "12";
      setMonthButtons();
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
      showBanner("Signed in. Trends are read-only.", true);
    }).catch(function (err) {
      showBanner(err.message || String(err));
    });
  });
  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message || String(err)); });
})();
