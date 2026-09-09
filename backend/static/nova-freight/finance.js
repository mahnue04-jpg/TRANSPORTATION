"use strict";

(function () {
  var selectedId = "";
  function $(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function identity() {
    var current = session() && session().getCurrent ? session().getCurrent() : null;
    return current && current.identity ? current.identity : null;
  }
  function isFinance() {
    var role = (identity() && identity().role) || "";
    return role === "admin" || role === "super_admin_support";
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
    var response = await fetch(path, Object.assign({}, options || {}, { headers: headers }));
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(errorText(body, "Request failed (" + response.status + ")"));
    return body;
  }
  async function loadBoard() {
    var rows = await api("/api/nova/freight/payouts");
    $("payout-list").innerHTML = rows.length
      ? "<ul class='proof-list'>" + rows.map(function (row) {
          return "<li><button type='button' class='secondary pick' data-id='" + row.payout_id + "'>" +
            row.shipment_id + "</button> · " + (row.carrier_name || row.carrier_id) +
            " · customer " + row.customer_amount +
            " · carrier " + row.carrier_payout_amount +
            " · margin " + row.amicor_margin_amount +
            " · payout " + row.payout_status +
            " · settlement " + (row.settlement_status || "none") +
            " · POP " + (row.has_pickup_proof ? "Yes" : "No") +
            " · POD " + (row.has_delivery_proof ? "Yes" : "No") + "</li>";
        }).join("") + "</ul>"
      : "<p>No payouts yet. Create one from a paid completed shipment.</p>";
    document.querySelectorAll(".finance-only").forEach(function (el) {
      el.classList.toggle("hidden", !isFinance());
    });
  }
  async function loadDetail(payoutId) {
    selectedId = payoutId;
    var rows = await api("/api/nova/freight/payouts");
    var row = rows.filter(function (item) { return item.payout_id === payoutId; })[0];
    $("payout-detail").classList.remove("hidden");
    $("payout-box").textContent = JSON.stringify(row, null, 2);
    try {
      var remit = await api("/api/nova/freight/payouts/" + encodeURIComponent(payoutId) + "/remittance");
      $("remittance-box").textContent = remit.remittance_text || JSON.stringify(remit, null, 2);
    } catch (_) {
      $("remittance-box").textContent = "Remittance appears after TEST payout execution.";
    }
  }
  async function renderApp() {
    var ident = identity();
    $("login-card").classList.add("hidden");
    $("app-shell").classList.remove("hidden");
    $("session-name").textContent = ident && (ident.name || ident.email) ? (ident.name || ident.email) : "Signed in";
    $("session-meta").textContent = (ident && ident.role) || "";
    await loadBoard();
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
    await renderApp();
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
    window.location.href = "/nova/freight/finance";
  });
  $("payout-list").addEventListener("click", async function (event) {
    var btn = event.target.closest(".pick");
    if (!btn) return;
    try { await loadDetail(btn.getAttribute("data-id")); } catch (err) { showBanner(err.message); }
  });
  async function act(path, body) {
    if (!selectedId) return;
    await api("/api/nova/freight/payouts/" + encodeURIComponent(selectedId) + path, {
      method: "POST",
      body: JSON.stringify(body || {})
    });
    await loadBoard();
    await loadDetail(selectedId);
  }
  $("adjust-payout").addEventListener("click", async function () {
    try {
      var form = $("adjust-form");
      await act("/adjust", { carrier_payout_amount: form.carrier_payout_amount.value, reason: form.reason.value });
      showBanner("Payout adjusted.", true);
    } catch (err) { showBanner(err.message); }
  });
  $("hold-payout").addEventListener("click", async function () {
    try { await act("/hold", { reason: $("adjust-form").reason.value || "Held for review" }); showBanner("Payout held.", true); }
    catch (err) { showBanner(err.message); }
  });
  $("approve-payout").addEventListener("click", async function () {
    try { await act("/approve"); showBanner("Payout approved for TEST execution.", true); }
    catch (err) { showBanner(err.message); }
  });
  $("execute-payout").addEventListener("click", async function () {
    try { await act("/execute"); showBanner("SIMULATED TEST payout marked paid. No money moved.", true); }
    catch (err) { showBanner(err.message); }
  });
  $("void-payout").addEventListener("click", async function () {
    try { await act("/void"); showBanner("Payout voided.", true); }
    catch (err) { showBanner(err.message); }
  });
  boot();
})();
