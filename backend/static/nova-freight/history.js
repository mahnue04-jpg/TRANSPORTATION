"use strict";

(function () {
  function $(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function identity() {
    var current = session() && session().getCurrent ? session().getCurrent() : null;
    return current && current.identity ? current.identity : null;
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
  async function api(path) {
    var headers = { "Content-Type": "application/json" };
    if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
    else if (token()) headers.Authorization = "Bearer " + token();
    var response = await fetch(path, { headers: headers });
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (response.status === 401) throw new Error("Session expired. Sign in again.");
    if (!response.ok) throw new Error(errorText(body, "Request failed (" + response.status + ")"));
    return body;
  }
  function routeShipmentId() {
    var match = window.location.pathname.match(/\/nova\/freight\/history\/([^/]+)$/);
    return match ? decodeURIComponent(match[1]) : "";
  }
  function when(value) {
    return value ? String(value).replace("T", " ").slice(0, 16) : "—";
  }
  async function loadDetail(shipmentId) {
    var row = await api("/api/nova/freight/history/" + encodeURIComponent(shipmentId));
    $("history-detail").classList.remove("hidden");
    $("history-box").textContent = JSON.stringify(row, null, 2);
  }
  async function renderApp() {
    var ident = identity();
    $("login-card").classList.add("hidden");
    $("app-shell").classList.remove("hidden");
    $("session-name").textContent = ident && (ident.name || ident.email) ? (ident.name || ident.email) : "Signed in";
    $("session-meta").textContent = (ident && ident.role) || "";
    var rows = await api("/api/nova/freight/history");
    $("history-list").innerHTML = rows.length
      ? "<ul class='proof-list wrap-list'>" + rows.map(function (row) {
          return "<li><a href='/nova/freight/history/" + encodeURIComponent(row.shipment_id) + "'>" + row.shipment_id + "</a> · " +
            (row.customer_name || "") + " · " + (row.pickup_city || "") + " → " + (row.delivery_city || "") +
            " · " + (row.assigned_carrier_name || row.assigned_carrier_id || "unassigned") +
            " · invoice " + (row.invoice_status || "none") +
            " · payout " + (row.carrier_payout_status || "none") +
            " · remittance " + (row.remittance_reference || "none") +
            " · completed " + when(row.completed_at) + "</li>";
        }).join("") + "</ul>"
      : "<p>No completed or cancelled freight shipments yet.</p>";
    var selected = routeShipmentId();
    if (selected) await loadDetail(selected);
  }
  async function boot() {
    if (session() && session().restore) session().restore();
    if (session() && session().ensureReady) {
      try { await session().ensureReady(); } catch (_) {}
    }
    if (!token()) {
      $("login-card").classList.remove("hidden");
      $("app-shell").classList.add("hidden");
      return;
    }
    try { await renderApp(); } catch (err) { showBanner(err.message); }
  }
  $("login-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: $("login-email").value, password: $("login-password").value })
    });
    var payload = await response.json();
    if (!response.ok) {
      showBanner(errorText(payload, "Sign-in failed"));
      return;
    }
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
    await renderApp();
  });
  $("sign-out").addEventListener("click", async function () {
    if (session() && session().logout) await session().logout();
    window.location.href = "/nova/freight/history";
  });
  boot();
})();
