"use strict";

(function () {
  var banner = document.getElementById("banner");
  var form = document.getElementById("signup-form");
  var offerCopy = document.getElementById("offer-copy");
  var offerSlots = document.getElementById("offer-slots");
  var paymentMode = document.getElementById("payment-mode");
  var submitBtn = document.getElementById("submit-btn");

  function show(message, ok) {
    banner.textContent = message;
    banner.classList.remove("hidden");
    banner.classList.toggle("ok", !!ok);
  }

  function field(id) {
    return (document.getElementById(id).value || "").trim();
  }

  fetch("/api/nova/signup/offer")
    .then(function (response) { return response.json(); })
    .then(function (offer) {
      if (offer.copy) offerCopy.textContent = offer.copy;
      if (offer.founding_available) {
        offerSlots.textContent = offer.founding_slots_remaining + " founding slots remaining of " + offer.founding_cap + ".";
      } else {
        offerSlots.textContent = "Founding slots are filled. New customers still receive 7-day introductory access, then $99/month.";
      }
      var mode = String(offer.payment_mode || "not_configured");
      if (mode === "live") paymentMode.textContent = "Secure checkout: LIVE production Stripe is ready.";
      else if (mode === "test") paymentMode.textContent = "Secure checkout: Stripe TEST mode is ready; no live charge.";
      else if (mode === "live_gated") paymentMode.textContent = "Secure checkout: live Stripe detected but production activation is still gated.";
      else if (mode === "test_incomplete") paymentMode.textContent = "Secure checkout: Stripe TEST configuration is incomplete.";
      else paymentMode.textContent = "Secure checkout is not configured yet.";
    })
    .catch(function () {
      offerSlots.textContent = "Offer details will be confirmed at checkout.";
      if (paymentMode) paymentMode.textContent = "Secure checkout readiness could not be confirmed.";
    });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    submitBtn.disabled = true;
    var selected = document.querySelector('input[name="signup_tier"]:checked');
    var tier = selected ? selected.value : "free";
    var endpoint = tier === "paid" ? "/api/nova/signup" : "/api/nova/signup/free";
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        business_name: field("business_name"),
        contact_name: field("contact_name"),
        email: field("email"),
        phone: field("phone"),
        industry: field("industry"),
        password: document.getElementById("password").value,
        terms_accepted: document.getElementById("terms_accepted").checked
      })
    })
      .then(function (response) {
        return response.json().then(function (body) {
          return { ok: response.ok, body: body };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          show((result.body && result.body.detail) || "Signup failed.");
          submitBtn.disabled = false;
          return;
        }
        if (result.body.checkout_url) {
          window.location.href = result.body.checkout_url;
          return;
        }
        if (result.body.status === "free" && result.body.login_ready) {
          show("Free AMICOR Nova account created. Sign in to start using your daily Nova access.", true);
          window.setTimeout(function () { window.location.href = "/nova"; }, 1200);
          return;
        }
        show("Account created, but the next step is not available yet.", false);
        submitBtn.disabled = false;
      })
      .catch(function () {
        show("Network error. Account was not confirmed.");
        submitBtn.disabled = false;
      });
  });
})();
