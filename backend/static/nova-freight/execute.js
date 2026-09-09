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
  function authHeaders(includeJson) {
    var headers = includeJson ? { "Content-Type": "application/json" } : {};
    if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
    else if (token()) headers.Authorization = "Bearer " + token();
    return headers;
  }
  async function api(path, options) {
    var headers = authHeaders(true);
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

  function bindPad(canvas) {
    if (!canvas || canvas._bound) return;
    canvas._bound = true;
    canvas._hasInk = false;
    var ctx = canvas.getContext("2d");
    var drawing = false;
    function pos(event) {
      var rect = canvas.getBoundingClientRect();
      var src = event.touches ? event.touches[0] : event;
      return {
        x: (src.clientX - rect.left) * (canvas.width / rect.width),
        y: (src.clientY - rect.top) * (canvas.height / rect.height)
      };
    }
    function start(event) {
      drawing = true;
      var point = pos(event);
      ctx.beginPath();
      ctx.moveTo(point.x, point.y);
      event.preventDefault();
    }
    function move(event) {
      if (!drawing) return;
      var point = pos(event);
      ctx.lineTo(point.x, point.y);
      ctx.strokeStyle = "#e8f2ff";
      ctx.lineWidth = 2;
      ctx.stroke();
      canvas._hasInk = true;
      event.preventDefault();
    }
    function end() { drawing = false; }
    canvas.addEventListener("mousedown", start);
    canvas.addEventListener("mousemove", move);
    canvas.addEventListener("mouseup", end);
    canvas.addEventListener("mouseleave", end);
    canvas.addEventListener("touchstart", start, { passive: false });
    canvas.addEventListener("touchmove", move, { passive: false });
    canvas.addEventListener("touchend", end);
  }
  function clearPad(canvas) {
    if (!canvas) return;
    var ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    canvas._hasInk = false;
  }
  function canvasBlob(canvas) {
    return new Promise(function (resolve) {
      if (!canvas || !canvas._hasInk) {
        resolve(null);
        return;
      }
      canvas.toBlob(function (blob) { resolve(blob); }, "image/png");
    });
  }
  function stamp(value) {
    return String(value || "").replace("T", " ").slice(0, 16);
  }
  function proofFlags(shipment) {
    return "Pickup proof: " + (shipment.has_pickup_proof ? "Yes" : "No") +
      " · Delivery proof: " + (shipment.has_delivery_proof ? "Yes" : "No");
  }
  function renderProofList(targetId, rows, shipmentId) {
    var el = $(targetId);
    if (!el) return;
    el.innerHTML = rows.length
      ? "<ul class='proof-list'>" + rows.map(function (row) {
          return "<li>" + row.proof_type + " · " + (row.original_filename || row.document_ref) +
            " · " + stamp(row.uploaded_at) +
            (row.uploader_role ? " · " + row.uploader_role : "") +
            (row.signer_name ? " · signer " + row.signer_name : "") +
            (row.notes ? " · " + row.notes : "") +
            " <button type='button' class='secondary open-proof' data-proof='" + row.proof_id + "' data-shipment='" + shipmentId + "'>View</button></li>";
        }).join("") + "</ul>"
      : "<p>No proof uploaded yet.</p>";
  }

  async function openProof(shipmentId, proofId) {
    var response = await fetch(
      "/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/proofs/" + encodeURIComponent(proofId) + "/file",
      { headers: authHeaders(false) }
    );
    if (response.status === 404) {
      showBanner("Proof is on file. No stored image is attached to this reference.", true);
      return;
    }
    if (!response.ok) throw new Error("Could not open proof");
    var blob = await response.blob();
    window.open(URL.createObjectURL(blob), "_blank", "noopener");
  }

  async function submitProof(shipmentId, form, canvas) {
    var type = form.proof_type.value;
    var notes = form.notes.value;
    var signer = form.signer_name.value;
    var file = form.file && form.file.files && form.file.files[0] ? form.file.files[0] : null;
    var signature = await canvasBlob(canvas);
    if (signature && !file) {
      file = new File([signature], type + ".png", { type: "image/png" });
    }
    var documentRef = "nfr-" + Date.now().toString(16) + Math.random().toString(16).slice(2, 10);
    if (file) {
      var body = new FormData();
      body.append("proof_type", type);
      body.append("document_ref", documentRef);
      body.append("notes", notes || "");
      body.append("signer_name", signer || "");
      if (type.indexOf("pickup") === 0) body.append("signer_role", "shipper");
      else body.append("signer_role", "receiver");
      body.append("file", file);
      var response = await fetch(
        "/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/proofs/upload",
        { method: "POST", headers: authHeaders(false), body: body }
      );
      var payload = null;
      try { payload = await response.json(); } catch (_) {}
      if (!response.ok) throw new Error(errorText(payload, "Proof upload failed"));
      return payload;
    }
    return api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/proofs", {
      method: "POST",
      body: JSON.stringify({
        proof_type: type,
        document_ref: documentRef,
        notes: notes || null,
        signer_name: signer || null,
        signer_role: type.indexOf("pickup") === 0 ? "shipper" : "receiver"
      })
    });
  }

  async function renderTimeline(shipmentId) {
    var events = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/events");
    $("timeline").innerHTML = events.length
      ? "<ol>" + events.map(function (event) {
          if (event.event_type && event.event_type !== "status_transition") {
            return "<li><strong>" + event.event_type + "</strong>" +
              (event.proof_id ? " · " + event.proof_id : "") +
              " · " + stamp(event.created_at) +
              (event.notes ? " · " + event.notes : "") + "</li>";
          }
          return "<li>" + event.status_before + " → <strong>" + event.status_after + "</strong> · " +
            stamp(event.created_at) +
            (event.notes ? " · " + event.notes : "") + "</li>";
        }).join("") + "</ol>"
      : "<p>No lifecycle events yet.</p>";
  }

  async function renderDetail(shipmentId) {
    var shipment = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId));
    var proofs = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/proofs");
    $("view-list").classList.add("hidden");
    $("view-detail").classList.remove("hidden");
    $("detail-id").textContent = shipment.shipment_id;
    $("detail-status").textContent = shipment.status;
    $("detail-carrier").textContent = "Assigned carrier: " + (shipment.assigned_carrier_id || "none");
    $("detail-pickup").textContent = "Pickup: " + loc(shipment, "pickup");
    $("detail-delivery").textContent = "Delivery: " + loc(shipment, "delivery");
    $("detail-load").textContent = "Load: " + shipment.commodity + " · " + (shipment.weight || "—") + " " + (shipment.weight_unit || "") + " · " + shipment.equipment_type;
    $("detail-proof-flags").textContent = proofFlags(shipment);
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
    var pickupStage = shipment.status === "arrived_pickup" || shipment.status === "picked_up";
    var deliveryStage = shipment.status === "arrived_delivery" || shipment.status === "delivered";
    var pickupRows = proofs.filter(function (row) { return String(row.proof_type).indexOf("pickup_") === 0; });
    var deliveryRows = proofs.filter(function (row) { return String(row.proof_type).indexOf("delivery_") === 0; });
    $("pickup-proof-card").classList.toggle("hidden", !(pickupStage || pickupRows.length || shipment.status === "completed"));
    $("delivery-proof-card").classList.toggle("hidden", !(deliveryStage || deliveryRows.length || shipment.status === "completed"));
    $("pickup-proof-form").classList.toggle("hidden", !pickupStage);
    $("delivery-proof-form").classList.toggle("hidden", !deliveryStage);
    renderProofList("pickup-proof-list", pickupRows, shipmentId);
    renderProofList("delivery-proof-list", deliveryRows, shipmentId);
    bindPad($("pickup-sig"));
    bindPad($("delivery-sig"));
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

  $("clear-pickup-sig").addEventListener("click", function () { clearPad($("pickup-sig")); });
  $("clear-delivery-sig").addEventListener("click", function () { clearPad($("delivery-sig")); });
  $("pickup-proof-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var shipmentId = routeShipmentId();
    if (!shipmentId || submitting) return;
    submitting = true;
    try {
      await submitProof(shipmentId, event.target, $("pickup-sig"));
      showBanner("Pickup proof saved.", true);
      event.target.reset();
      clearPad($("pickup-sig"));
      await renderDetail(shipmentId);
    } catch (err) {
      showBanner(err.message);
    } finally {
      submitting = false;
    }
  });
  $("delivery-proof-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var shipmentId = routeShipmentId();
    if (!shipmentId || submitting) return;
    submitting = true;
    try {
      await submitProof(shipmentId, event.target, $("delivery-sig"));
      showBanner("Delivery proof saved.", true);
      event.target.reset();
      clearPad($("delivery-sig"));
      await renderDetail(shipmentId);
    } catch (err) {
      showBanner(err.message);
    } finally {
      submitting = false;
    }
  });
  $("view-detail").addEventListener("click", async function (event) {
    var btn = event.target.closest(".open-proof");
    if (!btn) return;
    try {
      await openProof(btn.getAttribute("data-shipment"), btn.getAttribute("data-proof"));
    } catch (err) {
      showBanner(err.message);
    }
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
