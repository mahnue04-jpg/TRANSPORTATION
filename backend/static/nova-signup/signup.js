"use strict";

(function () {
  var banner = document.getElementById("banner");
  var form = document.getElementById("signup-form");
  var offerCopy = document.getElementById("offer-copy");
  var offerSlots = document.getElementById("offer-slots");
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
    })
    .catch(function () {
      offerSlots.textContent = "Offer details will be confirmed at checkout.";
    });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    submitBtn.disabled = true;
    fetch("/api/nova/signup", {
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
        show("Account created, but checkout is not available yet.", false);
        submitBtn.disabled = false;
      })
      .catch(function () {
        show("Network error. Account was not confirmed.");
        submitBtn.disabled = false;
      });
  });
})();
