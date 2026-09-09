"use strict";

(function () {
  var step = 1;
  var lastShipment = null;

  function $(id) {
    return document.getElementById(id);
  }

  function showBanner(message, ok) {
    var el = $("banner");
    el.textContent = message;
    el.classList.remove("hidden");
    el.classList.toggle("ok", !!ok);
  }

  function hideBanner() {
    $("banner").classList.add("hidden");
  }

  function session() {
    return window.AmiCorSession || null;
  }

  function token() {
    return session() && session().getAccessToken ? session().getAccessToken() : "";
  }

  function identity() {
    var current = session() && session().getCurrent ? session().getCurrent() : null;
    return current && current.identity ? current.identity : null;
  }

  function setView(name) {
    ["view-list", "view-form", "view-detail"].forEach(function (id) {
      $(id).classList.toggle("hidden", id !== "view-" + name);
    });
  }

  function routeName() {
    var path = window.location.pathname.replace(/\/+$/, "");
    if (path.indexOf("/nova/freight/shipments/") === 0) return "detail";
    if (path === "/nova/freight/shipments") return "list";
    if (path === "/nova/freight/new") return "form";
    return "list";
  }

  function routeShipmentId() {
    var match = window.location.pathname.match(/\/nova\/freight\/shipments\/([^/]+)$/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function formValues() {
    var form = $("freight-form");
    var data = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name) return;
      if (el.type === "checkbox") {
        data[el.name] = el.checked;
        return;
      }
      data[el.name] = el.value;
    });
    return data;
  }

  function emptyToNull(value) {
    if (value === undefined || value === null) return null;
    var text = String(value).trim();
    return text ? text : null;
  }

  function toIso(value) {
    var text = emptyToNull(value);
    if (!text) return null;
    var date = new Date(text);
    if (Number.isNaN(date.getTime())) return null;
    return date.toISOString();
  }

  function payloadFromForm() {
    var raw = formValues();
    return {
      customer_name: raw.customer_name,
      contact_name: emptyToNull(raw.contact_name),
      contact_phone: emptyToNull(raw.contact_phone),
      contact_email: emptyToNull(raw.contact_email),
      pickup_address: raw.pickup_address,
      pickup_city: raw.pickup_city,
      pickup_state: raw.pickup_state,
      pickup_zip: raw.pickup_zip,
      pickup_contact: emptyToNull(raw.pickup_contact),
      pickup_phone: emptyToNull(raw.pickup_phone),
      pickup_window_start: toIso(raw.pickup_window_start),
      pickup_window_end: toIso(raw.pickup_window_end),
      delivery_address: raw.delivery_address,
      delivery_city: raw.delivery_city,
      delivery_state: raw.delivery_state,
      delivery_zip: raw.delivery_zip,
      delivery_contact: emptyToNull(raw.delivery_contact),
      delivery_phone: emptyToNull(raw.delivery_phone),
      delivery_window_start: toIso(raw.delivery_window_start),
      delivery_window_end: toIso(raw.delivery_window_end),
      commodity: raw.commodity,
      quantity: emptyToNull(raw.quantity),
      weight: emptyToNull(raw.weight),
      weight_unit: raw.weight_unit || "lb",
      piece_count: emptyToNull(raw.piece_count),
      pallet_count: emptyToNull(raw.pallet_count),
      length_in: emptyToNull(raw.length_in),
      width_in: emptyToNull(raw.width_in),
      height_in: emptyToNull(raw.height_in),
      special_handling_notes: emptyToNull(raw.special_handling_notes),
      hazardous: !!raw.hazardous,
      temperature_controlled: !!raw.temperature_controlled,
      fragile: !!raw.fragile,
      equipment_type: raw.equipment_type || "cargo_van"
    };
  }

  function errorText(payload, fallback) {
    if (!payload) return fallback;
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail)) {
      return payload.detail.map(function (item) {
        return (item.loc ? item.loc.join(".") + ": " : "") + (item.msg || JSON.stringify(item));
      }).join(" ");
    }
    return fallback;
  }

  async function api(path, options) {
    var headers = { "Content-Type": "application/json" };
    if (session() && session().getAuthHeaders) {
      Object.assign(headers, session().getAuthHeaders());
    } else if (token()) {
      headers.Authorization = "Bearer " + token();
    }
    var response = await fetch(path, Object.assign({}, options || {}, { headers: headers }));
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (!response.ok) {
      throw new Error(errorText(body, "Request failed (" + response.status + ")"));
    }
    return body;
  }

  function renderStep() {
    Array.prototype.forEach.call(document.querySelectorAll(".step-dot"), function (btn) {
      btn.classList.toggle("active", Number(btn.getAttribute("data-step")) === step);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".step-panel"), function (panel) {
      panel.classList.toggle("hidden", Number(panel.getAttribute("data-step-panel")) !== step);
    });
    $("prev-step").classList.toggle("hidden", step === 1);
    $("next-step").classList.toggle("hidden", step === 7);
    $("submit-freight").classList.toggle("hidden", step !== 7);
    if (step === 6) {
      $("review-box").textContent = JSON.stringify(payloadFromForm(), null, 2);
    }
  }

  function cityLine(city, state, zip) {
    return [city, state, zip].filter(Boolean).join(", ");
  }

  function showDetail(shipment, saved) {
    lastShipment = shipment;
    $("detail-confirm").textContent = saved
      ? "The freight request was saved and is ready for later dispatch."
      : "Shipment details";
    $("detail-id").textContent = shipment.shipment_id;
    $("detail-status").textContent = shipment.status;
    $("detail-pickup").textContent = shipment.pickup_address + " · " + cityLine(shipment.pickup_city, shipment.pickup_state, shipment.pickup_zip);
    $("detail-delivery").textContent = shipment.delivery_address + " · " + cityLine(shipment.delivery_city, shipment.delivery_state, shipment.delivery_zip);
    $("detail-commodity").textContent = shipment.commodity;
    $("detail-equipment").textContent = shipment.equipment_type;
    if ($("detail-proof-flags")) {
      $("detail-proof-flags").textContent = "Pickup proof: " + (shipment.has_pickup_proof ? "Yes" : "No") +
        " · Delivery proof: " + (shipment.has_delivery_proof ? "Yes" : "No");
    }
    setView("detail");
  }

  async function loadList() {
    var rows = await api("/api/nova/freight/shipments");
    var body = $("shipment-rows");
    body.innerHTML = "";
    if (!rows.length) {
      body.innerHTML = "<tr><td colspan='7'>No freight requests yet.</td></tr>";
      return;
    }
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td><a href='/nova/freight/shipments/" + encodeURIComponent(row.shipment_id) + "'>" + row.shipment_id + "</a></td>" +
        "<td>" + cityLine(row.pickup_city, row.pickup_state, row.pickup_zip) + "</td>" +
        "<td>" + cityLine(row.delivery_city, row.delivery_state, row.delivery_zip) + "</td>" +
        "<td>" + (row.commodity || "") + "</td>" +
        "<td>" + (row.equipment_type || "") + "</td>" +
        "<td><span class='status'>" + row.status + "</span></td>" +
        "<td>" + String(row.created_at || "").replace("T", " ").slice(0, 16) + "</td>";
      body.appendChild(tr);
    });
  }

  async function renderApp() {
    var ident = identity();
    $("login-card").classList.add("hidden");
    $("app-shell").classList.remove("hidden");
    $("session-name").textContent = ident && (ident.name || ident.email) ? (ident.name || ident.email) : "Signed in";
    $("session-meta").textContent = ((ident && ident.role) || "") + (ident && ident.organizationName ? " · " + ident.organizationName : "");
    var view = routeName();
    if (view === "form") {
      setView("form");
      renderStep();
      return;
    }
    if (view === "detail") {
      var shipment = lastShipment && lastShipment.shipment_id === routeShipmentId()
        ? lastShipment
        : await api("/api/nova/freight/shipments/" + encodeURIComponent(routeShipmentId()));
      showDetail(shipment, false);
      return;
    }
    setView("list");
    await loadList();
  }

  async function boot() {
    hideBanner();
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
    hideBanner();
    var response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: $("login-email").value,
        password: $("login-password").value
      })
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
    window.location.href = "/nova/freight";
  });

  document.querySelectorAll(".step-dot").forEach(function (btn) {
    btn.addEventListener("click", function () {
      step = Number(btn.getAttribute("data-step"));
      renderStep();
    });
  });

  $("prev-step").addEventListener("click", function () {
    step = Math.max(1, step - 1);
    renderStep();
  });

  $("next-step").addEventListener("click", function () {
    step = Math.min(7, step + 1);
    renderStep();
  });

  $("freight-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    hideBanner();
    try {
      var created = await api("/api/nova/freight/shipments", {
        method: "POST",
        body: JSON.stringify(payloadFromForm())
      });
      history.replaceState({}, "", "/nova/freight/shipments/" + encodeURIComponent(created.shipment_id));
      showBanner("Freight request saved as " + created.shipment_id + " (" + created.status + ").", true);
      showDetail(created, true);
    } catch (err) {
      showBanner(err.message || "Could not save freight request");
    }
  });

  boot();
})();
