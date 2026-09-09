"use strict";

(function () {
  var NEXT = {
    accepted: { status: "en_route_to_pickup", label: "Start Trip to Pickup" },
    en_route_to_pickup: { status: "arrived_pickup", label: "Arrived at Pickup" },
    arrived_pickup: { status: "picked_up", label: "Confirm Pickup" },
    picked_up: { status: "in_transit", label: "Start Transit" },
    in_transit: { status: "arrived_delivery", label: "Arrived at Delivery" },
    arrived_delivery: { status: "delivered", label: "Confirm Delivered" },
    delivered: { status: "completed", label: "Complete Shipment" }
  };
  var submitting = false;

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
  function routeShipmentId() {
    var match = window.location.pathname.match(/\/nova\/freight\/carrier\/shipments\/([^/]+)$/);
    return match ? decodeURIComponent(match[1]) : "";
  }
  function loc(row, prefix) {
    return [row[prefix + "_address"], row[prefix + "_city"], row[prefix + "_state"], row[prefix + "_zip"]].filter(Boolean).join(", ");
  }

  async function renderTimeline(shipmentId) {
    var events = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/events");
    $("timeline").innerHTML = events.length
      ? "<ol>" + events.map(function (event) {
          return "<li>" + event.status_before + " → <strong>" + event.status_after + "</strong> · " +
            String(event.created_at || "").replace("T", " ").slice(0, 16) +
            (event.notes ? " · " + event.notes : "") + "</li>";
        }).join("") + "</ol>"
      : "<p>No lifecycle events yet.</p>";
  }

  async function renderDetail(shipmentId) {
    var shipment = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId));
    $("view-list").classList.add("hidden");
    $("view-detail").classList.remove("hidden");
    $("detail-id").textContent = shipment.shipment_id;
    $("detail-status").textContent = shipment.status;
    $("detail-carrier").textContent = "Assigned carrier: " + (shipment.assigned_carrier_id || "none");
    $("detail-pickup").textContent = "Pickup: " + loc(shipment, "pickup");
    $("detail-delivery").textContent = "Delivery: " + loc(shipment, "delivery");
    $("detail-load").textContent = "Load: " + shipment.commodity + " · " + (shipment.weight || "—") + " " + (shipment.weight_unit || "") + " · " + shipment.equipment_type;
    var next = NEXT[shipment.status];
    var btn = $("next-action");
    if (next && shipment.status !== "completed") {
      btn.classList.remove("hidden");
      btn.disabled = false;
      btn.textContent = next.label;
      btn.setAttribute("data-status", next.status);
    } else {
      btn.classList.add("hidden");
    }
    await renderTimeline(shipmentId);
  }

  async function renderList() {
    $("view-detail").classList.add("hidden");
    $("view-list").classList.remove("hidden");
    var rows = await api("/api/nova/freight/carrier/shipments");
    $("active-list").innerHTML = rows.length
      ? rows.map(function (row) {
          return "<p><a href='/nova/freight/carrier/shipments/" + encodeURIComponent(row.shipment_id) + "'>" +
            row.shipment_id + "</a> · " + row.status + " · " + row.pickup_city + " → " + row.delivery_city + "</p>";
        }).join("")
      : "<p>No active assigned shipments.</p>";
  }

  async function renderApp() {
    var ident = identity();
    $("login-card").classList.add("hidden");
    $("app-shell").classList.remove("hidden");
    $("session-name").textContent = ident && (ident.name || ident.email) ? (ident.name || ident.email) : "Signed in";
    $("session-meta").textContent = (ident && ident.role) || "";
    var shipmentId = routeShipmentId();
    if (shipmentId) await renderDetail(shipmentId);
    else await renderList();
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
    window.location.href = "/nova/freight/carrier/shipments";
  });

  $("next-action").addEventListener("click", async function () {
    if (submitting) return;
    var shipmentId = routeShipmentId();
    var status = $("next-action").getAttribute("data-status");
    if (!shipmentId || !status) return;
    submitting = true;
    $("next-action").disabled = true;
    try {
      var updated = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/status", {
        method: "POST",
        body: JSON.stringify({ status: status })
      });
      showBanner("Status is now " + updated.status + ".", true);
      await renderDetail(shipmentId);
    } catch (err) {
      showBanner(err.message);
      $("next-action").disabled = false;
    } finally {
      submitting = false;
    }
  });

  boot();
})();
