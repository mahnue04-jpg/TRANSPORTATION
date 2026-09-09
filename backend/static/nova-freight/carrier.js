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
    if (Array.isArray(payload.detail)) {
      return payload.detail.map(function (item) { return item.msg || JSON.stringify(item); }).join(" ");
    }
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
  function loc(city, state) { return [city, state].filter(Boolean).join(", ") || "—"; }
  function windowText(start, end) {
    if (!start && !end) return "Flexible";
    return String(start || "").replace("T", " ").slice(0, 16) + " → " + String(end || "").replace("T", " ").slice(0, 16);
  }

  async function loadOffers() {
    var offers = await api("/api/nova/freight/offers");
    var root = $("offer-cards");
    if (!offers.length) {
      root.innerHTML = "<p>No freight offers for this carrier account.</p>";
      return;
    }
    root.innerHTML = offers.map(function (offer) {
      var actions = offer.status === "pending"
        ? "<div class='actions'><button type='button' data-act='accept' data-id='" + offer.offer_id + "'>ACCEPT</button>" +
          "<button type='button' class='secondary' data-act='decline' data-id='" + offer.offer_id + "'>DECLINE</button></div>"
        : (offer.status === "accepted"
          ? "<p><strong>Assigned to you.</strong> <a href='/nova/freight/carrier/shipments/" + encodeURIComponent(offer.shipment_id) + "'>Open execution</a></p>"
          : "<p>This offer is closed.</p>");
      return "<article class='card' style='margin-top:12px'>" +
        "<p><strong>" + offer.shipment_id + "</strong> · <span class='status'>" + offer.status + "</span></p>" +
        "<p>Pickup: " + loc(offer.pickup_city, offer.pickup_state) + "</p>" +
        "<p>Destination: " + loc(offer.delivery_city, offer.delivery_state) + "</p>" +
        "<p>Pickup window: " + windowText(offer.pickup_window_start, offer.pickup_window_end) + "</p>" +
        "<p>Delivery window: " + windowText(offer.delivery_window_start, offer.delivery_window_end) + "</p>" +
        "<p>Commodity: " + (offer.commodity || "—") + "</p>" +
        "<p>Weight: " + (offer.weight || "—") + " " + (offer.weight_unit || "") + "</p>" +
        "<p>Equipment: " + (offer.equipment_type || "—") + "</p>" +
        "<p>Offered rate: " + (offer.offered_rate != null ? offer.offered_rate + " " + offer.currency : "placeholder / not set") + "</p>" +
        "<p>Shipment status: " + (offer.shipment_status || "—") + "</p>" +
        actions + "</article>";
    }).join("");
  }

  async function renderApp() {
    var ident = identity();
    $("login-card").classList.add("hidden");
    $("app-shell").classList.remove("hidden");
    $("session-name").textContent = ident && (ident.name || ident.email) ? (ident.name || ident.email) : "Signed in";
    $("session-meta").textContent = (ident && ident.role) || "";
    await loadOffers();
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
    window.location.href = "/nova/freight/carrier/offers";
  });
  $("offer-cards").addEventListener("click", async function (event) {
    var btn = event.target.closest("button[data-act]");
    if (!btn) return;
    var act = btn.getAttribute("data-act");
    var id = btn.getAttribute("data-id");
    try {
      var result = await api("/api/nova/freight/offers/" + encodeURIComponent(id) + "/" + act, { method: "POST" });
      if (act === "accept") showBanner("Assigned. Shipment " + result.shipment_id + " is accepted. Pickup has not started.", true);
      else showBanner("Offer declined.", true);
      await loadOffers();
    } catch (err) {
      showBanner(err.message);
      await loadOffers();
    }
  });

  boot();
})();
