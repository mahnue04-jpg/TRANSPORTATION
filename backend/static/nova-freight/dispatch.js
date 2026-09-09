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
  function city(row, prefix) {
    return [row[prefix + "_city"], row[prefix + "_state"]].filter(Boolean).join(", ");
  }
  function windowText(start, end) {
    if (!start && !end) return "—";
    return String(start || "").replace("T", " ").slice(0, 16) + " → " + String(end || "").replace("T", " ").slice(0, 16);
  }

  async function loadBoard() {
    var form = $("filter-form");
    var params = new URLSearchParams();
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name) return;
      if (el.type === "checkbox") {
        if (el.checked) params.set(el.name, "true");
        return;
      }
      if (el.value) params.set(el.name, el.type === "datetime-local" ? new Date(el.value).toISOString() : el.value);
    });
    var rows = await api("/api/nova/freight/dispatch/shipments?" + params.toString());
    var body = $("board-rows");
    body.innerHTML = "";
    if (!rows.length) {
      body.innerHTML = "<tr><td colspan='13'>No dispatch-ready freight shipments.</td></tr>";
      return;
    }
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td><button type='button' class='secondary pick' data-id='" + row.shipment_id + "'>" + row.shipment_id + "</button></td>" +
        "<td>" + (row.customer_name || "") + "</td>" +
        "<td>" + city(row, "pickup") + "</td>" +
        "<td>" + city(row, "delivery") + "</td>" +
        "<td>" + windowText(row.pickup_window_start, row.pickup_window_end) + "</td>" +
        "<td>" + windowText(row.delivery_window_start, row.delivery_window_end) + "</td>" +
        "<td>" + (row.commodity || "") + "</td>" +
        "<td>" + (row.weight || "") + " " + (row.weight_unit || "") + "</td>" +
        "<td>" + (row.equipment_type || "") + "</td>" +
        "<td><span class='status'>" + row.status + "</span></td>" +
        "<td>" + String(row.last_status_at || row.updated_at || "").replace("T", " ").slice(0, 16) + "</td>" +
        "<td>" + String(row.created_at || "").replace("T", " ").slice(0, 16) + "</td>" +
        "<td>" + (row.assigned_carrier_name || row.assigned_carrier_id || "—") + "</td>";
      body.appendChild(tr);
    });
  }

  async function loadDetail(shipmentId) {
    selectedId = shipmentId;
    var shipment = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId));
    var offers = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/offers");
    var carriers = await api("/api/nova/freight/carriers?equipment_type=" + encodeURIComponent(shipment.equipment_type || ""));
    $("detail-card").classList.remove("hidden");
    $("detail-id").textContent = shipment.shipment_id;
    $("detail-status").textContent = shipment.status;
    $("detail-assigned").textContent = shipment.assigned_carrier_id
      ? "Assigned / accepted carrier: " + shipment.assigned_carrier_id
      : "No carrier assigned yet.";
    $("detail-last").textContent = "Last status update: " + String(shipment.last_status_at || shipment.updated_at || "—").replace("T", " ").slice(0, 16);
    $("detail-proof-flags").textContent = "Pickup proof: " + (shipment.has_pickup_proof ? "Yes" : "No") +
      " · Delivery proof: " + (shipment.has_delivery_proof ? "Yes" : "No");
    await loadCommercial(shipmentId, shipment);
    var proofs = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/proofs");
    $("proof-list").innerHTML = proofs.length
      ? "<ul class='proof-list'>" + proofs.map(function (row) {
          return "<li>" + row.proof_type + " · " + (row.original_filename || row.document_ref) +
            " · " + String(row.uploaded_at || "").replace("T", " ").slice(0, 16) +
            (row.uploader_role ? " · " + row.uploader_role : "") +
            (row.signer_name ? " · signer " + row.signer_name : "") +
            (row.notes ? " · " + row.notes : "") +
            (row.proof_id ? " · " + row.proof_id : "") + "</li>";
        }).join("") + "</ul>"
      : "<p>No pickup or delivery proof yet.</p>";
    var events = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/events");
    $("timeline").innerHTML = events.length
      ? "<ol>" + events.map(function (event) {
          if (event.event_type && event.event_type !== "status_transition") {
            return "<li><strong>" + event.event_type + "</strong>" +
              (event.proof_id ? " · " + event.proof_id : "") +
              " · " + String(event.created_at || "").replace("T", " ").slice(0, 16) + "</li>";
          }
          return "<li>" + event.status_before + " → <strong>" + event.status_after + "</strong> · " +
            String(event.created_at || "").replace("T", " ").slice(0, 16) + "</li>";
        }).join("") + "</ol>"
      : "<p>No execution events yet.</p>";
    $("carrier-list").innerHTML = carriers.length
      ? carriers.map(function (carrier) {
          return "<label><input type='checkbox' name='carrier' value='" + carrier.carrier_id + "' /> " +
            carrier.name + " · " + carrier.equipment_type + " · " + (carrier.service_area || "no area") +
            " · " + carrier.availability + "</label>";
        }).join("")
      : "<p>No eligible active carriers.</p>";
    $("offer-list").innerHTML = offers.length
      ? "<ul>" + offers.map(function (offer) {
          var action = offer.status === "pending"
            ? " <button type='button' class='secondary cancel-offer' data-offer='" + offer.offer_id + "'>Cancel</button>"
            : "";
          return "<li>" + offer.offer_id + " · " + (offer.carrier_name || offer.carrier_id) + " · " + offer.status + action + "</li>";
        }).join("") + "</ul>"
      : "<p>No offers yet.</p>";
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
    window.location.href = "/nova/freight/dispatch";
  });
  $("filter-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try { await loadBoard(); } catch (err) { showBanner(err.message); }
  });
  $("board-rows").addEventListener("click", async function (event) {
    var btn = event.target.closest(".pick");
    if (!btn) return;
    try { await loadDetail(btn.getAttribute("data-id")); } catch (err) { showBanner(err.message); }
  });
  async function loadCommercial(shipmentId, shipment) {
    var quote = null;
    var invoice = null;
    var payout = null;
    var eligibility = null;
    try { quote = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/quote"); } catch (_) {}
    try { invoice = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/invoice"); } catch (_) {}
    try { payout = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/payout"); } catch (_) {}
    try { eligibility = await api("/api/nova/freight/shipments/" + encodeURIComponent(shipmentId) + "/payout/eligibility"); } catch (_) {}
    $("commercial-summary").textContent =
      "Quote: " + (quote ? quote.quoted_amount + " " + quote.currency + " (" + quote.pricing_status + ")" : "none") +
      " · Invoice: " + (invoice ? invoice.invoice_status + " " + invoice.total_amount : "none") +
      " · Customer amount: " + (quote ? quote.total_customer_amount : "—") +
      " · Est. carrier cost: " + (quote ? quote.estimated_carrier_cost : "—") +
      " · Est. AMICOR margin: " + (quote ? quote.estimated_amicor_margin : shipment.amicor_margin || "—") +
      (invoice && invoice.paid_at ? " · Paid: " + String(invoice.paid_at).replace("T", " ").slice(0, 16) : "") +
      (invoice && invoice.stripe_payment_intent_id ? " · Stripe TEST: " + invoice.stripe_payment_intent_id : "");
    $("quote-breakdown").textContent = quote
      ? JSON.stringify({
          suggested_amount: quote.suggested_amount,
          quoted_amount: quote.quoted_amount,
          base_rate: quote.base_rate,
          mileage_amount: quote.mileage_amount,
          special_handling_surcharge: quote.special_handling_surcharge,
          fuel_surcharge: quote.fuel_surcharge,
          tax_amount: quote.tax_amount,
          estimated_carrier_cost: quote.estimated_carrier_cost,
          estimated_amicor_margin: quote.estimated_amicor_margin
        }, null, 2)
      : "No quote yet.";
    $("invoice-box").textContent = invoice
      ? "Invoice " + invoice.invoice_id + " · " + invoice.invoice_status + " · " + invoice.total_amount + " " + invoice.currency
      : "No invoice yet. Create after completion.";
    $("payout-box").textContent = payout
      ? "Payout " + payout.payout_id + " · " + payout.payout_status + " · carrier " + payout.carrier_payout_amount + " · margin " + payout.amicor_margin_amount + (payout.proof_warning ? " · " + payout.proof_warning : "")
      : (eligibility
        ? (eligibility.eligible ? "Payout eligible. Create a pending payout after the customer invoice is paid." : "Payout not eligible: " + (eligibility.reasons || []).join("; "))
        : "No payout yet.");
  }
  function quotePayload() {
    var form = $("quote-form");
    var miles = form.estimated_miles.value;
    var override = form.quoted_amount.value;
    return {
      estimated_miles: miles ? miles : null,
      quoted_amount: override ? override : null,
      quote_notes: form.quote_notes.value || null,
      customer_notes: form.customer_notes.value || null
    };
  }
  $("suggest-quote").addEventListener("click", async function () {
    if (!selectedId) return;
    try {
      var suggested = await api("/api/nova/freight/shipments/" + encodeURIComponent(selectedId) + "/quote/suggest", {
        method: "POST",
        body: JSON.stringify(quotePayload())
      });
      $("quote-breakdown").textContent = JSON.stringify(suggested, null, 2);
      showBanner("Suggested quote is " + suggested.suggested_amount + ".", true);
    } catch (err) { showBanner(err.message); }
  });
  $("save-quote").addEventListener("click", async function () {
    if (!selectedId) return;
    try {
      await api("/api/nova/freight/shipments/" + encodeURIComponent(selectedId) + "/quote", {
        method: "POST",
        body: JSON.stringify(quotePayload())
      });
      showBanner("Quote saved.", true);
      await loadDetail(selectedId);
    } catch (err) { showBanner(err.message); }
  });
  $("finalize-quote").addEventListener("click", async function () {
    if (!selectedId) return;
    try {
      await api("/api/nova/freight/shipments/" + encodeURIComponent(selectedId) + "/quote/finalize", { method: "POST" });
      showBanner("Quote finalized.", true);
      await loadDetail(selectedId);
    } catch (err) { showBanner(err.message); }
  });
  $("create-invoice").addEventListener("click", async function () {
    if (!selectedId) return;
    try {
      await api("/api/nova/freight/shipments/" + encodeURIComponent(selectedId) + "/invoice", { method: "POST" });
      await api("/api/nova/freight/shipments/" + encodeURIComponent(selectedId) + "/invoice/finalize", { method: "POST" });
      showBanner("Invoice is ready for TEST payment.", true);
      await loadDetail(selectedId);
    } catch (err) { showBanner(err.message); }
  });
  $("create-payout").addEventListener("click", async function () {
    if (!selectedId) return;
    try {
      await api("/api/nova/freight/shipments/" + encodeURIComponent(selectedId) + "/payout", { method: "POST" });
      showBanner("Pending carrier payout created. Finance approval is admin-only.", true);
      await loadDetail(selectedId);
    } catch (err) { showBanner(err.message); }
  });

  $("send-offers").addEventListener("click", async function () {
    var ids = Array.prototype.map.call(document.querySelectorAll("input[name='carrier']:checked"), function (el) { return el.value; });
    if (!selectedId || !ids.length) {
      showBanner("Select a shipment and at least one carrier.");
      return;
    }
    try {
      await api("/api/nova/freight/shipments/" + encodeURIComponent(selectedId) + "/offers", {
        method: "POST",
        body: JSON.stringify({ carrier_ids: ids })
      });
      showBanner("Offers sent.", true);
      await loadBoard();
      await loadDetail(selectedId);
    } catch (err) {
      showBanner(err.message);
    }
  });
  $("offer-list").addEventListener("click", async function (event) {
    var btn = event.target.closest(".cancel-offer");
    if (!btn) return;
    try {
      await api("/api/nova/freight/offers/" + encodeURIComponent(btn.getAttribute("data-offer")) + "/cancel", { method: "POST" });
      showBanner("Offer cancelled.", true);
      await loadBoard();
      await loadDetail(selectedId);
    } catch (err) {
      showBanner(err.message);
    }
  });

  boot();
})();
