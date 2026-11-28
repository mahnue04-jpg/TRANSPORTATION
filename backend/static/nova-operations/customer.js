"use strict";
(function () {
  var PACKAGES = {
    starter: {label: "Starter Plan", amount: "$9.99"},
    starter_49: {label: "Starter Task", amount: "$49"},
    launch_99: {label: "Launch Operations", amount: "$99"},
    business_299: {label: "Business Operations", amount: "$299"}
  };

  function el(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function gate(value) { return value === "test" || value === "live" ? value : "closed"; }
  function status(message) { el("status").textContent = message; }

  function selectedPackage() {
    var key = new URLSearchParams(window.location.search).get("operations_package") || "";
    return Object.prototype.hasOwnProperty.call(PACKAGES, key) ? key : "";
  }

  async function api(path, options) {
    var headers = {"Accept": "application/json"};
    if (options && options.headers) Object.assign(headers, options.headers);
    if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
    else if (token()) headers.Authorization = "Bearer " + token();
    var request = Object.assign({cache: "no-store", credentials: "same-origin"}, options || {});
    request.headers = headers;
    var response = await fetch(path, request);
    var body = null;
    try { body = await response.json(); } catch (err) { body = null; }
    if (!response.ok) {
      var error = new Error("Request was not accepted");
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return body;
  }

  function showAccount(on) {
    el("account").hidden = !on;
    el("login-form").hidden = on;
  }

  function describeGates(fulfillment) {
    if (!fulfillment) return "Access gate: closed";
    var names = ["gate", "binding_gate", "delivery_gate", "adapter_gate", "execution_gate"];
    return names.filter(function (name) { return name in fulfillment; }).map(function (name) {
      return name.replace(/_/g, " ") + ": " + gate(fulfillment[name]);
    }).join(". ");
  }

  async function loadAccount() {
    var key = selectedPackage();
    showAccount(true);
    el("continue-payment").disabled = true;
    el("starter-workspace").hidden = key !== "starter";
    if (!key) {
      el("package-label").textContent = "No package selected";
      el("package-summary").textContent = "Return to pricing and choose Starter Plan, Starter Task, Launch Operations, or Business Operations.";
      el("gate-summary").textContent = "Access gate: closed";
      el("deliveries").textContent = "No package is selected.";
      return;
    }
    var known = PACKAGES[key];
    var intent = await api("/api/nova/operations/checkout?package=" + encodeURIComponent(key));
    el("package-label").textContent = intent.label || known.label;
    el("package-summary").textContent = known.amount + " · authenticated checkout · payment session " + (intent.stripe_session_created ? "open" : "not opened");
    el("gate-summary").textContent = describeGates(intent.fulfillment) + ". Public sales: " + (intent.sales_enabled === true ? "open" : "closed") + ".";
    el("continue-payment").disabled = intent.sales_enabled !== true || intent.executes_work === true;
    el("continue-payment").dataset.package = key;
    try {
      var deliveries = await api("/api/nova/work/operations/customer/deliveries");
      var rows = deliveries && Array.isArray(deliveries.deliveries) ? deliveries.deliveries : [];
      el("deliveries").textContent = rows.length ? rows.length + " delivery available on this account." : "No delivery is available on this account.";
    } catch (err) {
      el("deliveries").textContent = err.status === 401 ? "Sign in to see deliveries." : "Delivery gate: closed";
    }
  }

  async function boot() {
    if (session() && session().restore) session().restore();
    if (new URLSearchParams(window.location.search).get("signin") === "1") el("login-email").focus();
    if (!token()) {
      showAccount(false);
      status("Sign in with your Operations account.");
      return;
    }
    try {
      await loadAccount();
      status("Signed in. No payment was opened.");
    } catch (err) {
      showAccount(false);
      status(err.status === 401 ? "Sign in again to continue." : "This account cannot open Operations checkout.");
    }
  }

  el("login-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    status("Checking your account…");
    var response = await fetch("/api/auth/login", {
      method: "POST",
      headers: {"Content-Type": "application/json", "Accept": "application/json"},
      body: JSON.stringify({email: el("login-email").value, password: el("login-password").value})
    });
    var payload = null;
    try { payload = await response.json(); } catch (err) { payload = null; }
    if (!response.ok || !payload || !payload.access_token) {
      status("Sign-in was not accepted.");
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
    el("login-password").value = "";
    try {
      await loadAccount();
      status("Signed in. No payment was opened.");
    } catch (err) {
      status("This account cannot open Operations checkout.");
    }
  });

  el("continue-payment").addEventListener("click", async function () {
    var key = el("continue-payment").dataset.package || "";
    if (!PACKAGES[key] || el("continue-payment").disabled) return;
    el("continue-payment").disabled = true;
    try {
      var created = await api("/api/nova/operations/checkout", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({package: key})
      });
      if (created && created.sales_enabled === true && typeof created.checkout_url === "string" && created.checkout_url.indexOf("https://checkout.stripe.com/") === 0) {
        window.location.assign(created.checkout_url);
        return;
      }
      status("Payment stayed closed.");
    } catch (err) {
      status("Payment stayed closed.");
    }
  });

  boot();
})();
