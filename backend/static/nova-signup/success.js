"use strict";

(function () {
  var params = new URLSearchParams(window.location.search);
  var signupId = params.get("signup_id") || "";
  var statusCopy = document.getElementById("status-copy");
  var banner = document.getElementById("banner");
  var loginForm = document.getElementById("login-form");

  function show(message, ok) {
    banner.textContent = message;
    banner.classList.remove("hidden");
    banner.classList.toggle("ok", !!ok);
  }

  function refresh() {
    if (!signupId) return Promise.resolve();
    return fetch("/api/nova/signup/" + encodeURIComponent(signupId))
      .then(function (response) { return response.json(); })
      .then(function (body) {
        if (body.login_ready) {
          statusCopy.textContent = "Your isolated AMICOR Nova tenant is active. 7-day introductory access has started.";
          show("You can sign in and open Nova Today / Command Center.", true);
        } else {
          statusCopy.textContent = "Status: " + (body.status || "pending") + ". Activation happens after the Stripe webhook confirms checkout.";
        }
        if (body.email) document.getElementById("login-email").value = body.email;
        if (body.offer && body.offer.copy) document.getElementById("offer-copy").textContent = body.offer.copy;
      });
  }

  refresh();
  setInterval(refresh, 4000);

  loginForm.addEventListener("submit", function (event) {
    event.preventDefault();
    fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: document.getElementById("login-email").value,
        password: document.getElementById("login-password").value
      })
    })
      .then(function (response) {
        return response.json().then(function (body) {
          return { ok: response.ok, body: body };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          show((result.body && result.body.detail) || "Sign-in failed.");
          return;
        }
        if (window.AmiCorSession && window.AmiCorSession.start) {
          window.AmiCorSession.start({
            userId: result.body.user_id,
            email: result.body.email,
            name: result.body.display_name,
            role: result.body.role,
            accessToken: result.body.access_token,
            refreshToken: result.body.refresh_token,
            organizationId: result.body.organization_id,
            organization_name: result.body.organization_name,
            authorizedRoles: result.body.authorized_roles
          });
        }
        window.location.href = "/nova/today";
      })
      .catch(function () {
        show("Network error during sign-in.");
      });
  });
})();
