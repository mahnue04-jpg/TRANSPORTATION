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
  function metric(label, value) {
    return "<article class='metric'><p class='subtitle'>" + label + "</p><strong>" + value + "</strong></article>";
  }
  async function renderApp() {
    var ident = identity();
    $("login-card").classList.add("hidden");
    $("app-shell").classList.remove("hidden");
    $("session-name").textContent = ident && (ident.name || ident.email) ? (ident.name || ident.email) : "Signed in";
    $("session-meta").textContent = (ident && ident.role) || "";
    var data = await api("/api/nova/freight/ops/summary");
    $("ops-metrics").innerHTML = [
      metric("Awaiting dispatch", data.awaiting_dispatch),
      metric("Offered", data.offered),
      metric("Accepted / active", data.accepted_active),
      metric("In transit", data.in_transit),
      metric("Completed today", data.completed_today),
      metric("Unpaid invoices", data.unpaid_invoices),
      metric("Paid invoices", data.paid_invoices),
      metric("Pending payouts", data.pending_payouts),
      metric("Approved payouts", data.approved_payouts),
      metric("Simulated / paid payouts", data.paid_payouts),
      metric("Held payouts", data.held_payouts),
      metric("Gross customer revenue", data.gross_customer_revenue + " " + data.currency),
      metric("Carrier payout total", data.carrier_payout_total + " " + data.currency),
      metric("AMICOR margin estimate", data.amicor_margin_estimate + " " + data.currency)
    ].join("");
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
    try { await renderApp(); } catch (err) {
      showBanner(err.message);
      if (String(err.message).indexOf("Session expired") === 0) {
        $("login-card").classList.remove("hidden");
        $("app-shell").classList.add("hidden");
      }
    }
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
    window.location.href = "/nova/freight/ops";
  });
  boot();
})();
