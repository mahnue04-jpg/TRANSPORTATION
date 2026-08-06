(function () {
  "use strict";

  function initNav() {
    var toggle = document.querySelector("[data-nav-toggle]");
    var nav = document.querySelector("[data-site-nav]");
    if (!toggle || !nav) return;

    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        nav.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
      });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("is-open")) {
        nav.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.focus();
      }
    });
  }

  function setFormMessage(form, kind, message) {
    var status = form.querySelector("[data-form-status]");
    var error = form.querySelector("[data-form-error]");
    if (status) {
      status.classList.remove("is-visible");
      status.textContent = "";
    }
    if (error) {
      error.hidden = true;
      error.textContent = "";
    }
    if (kind === "success" && status) {
      status.textContent = message;
      status.classList.add("is-visible");
      status.focus && status.focus();
    }
    if (kind === "error" && error) {
      error.hidden = false;
      error.textContent = message;
    }
  }

  function collectPayload(form) {
    var data = new FormData(form);
    var leadType = form.getAttribute("data-lead-type") || "contact";
    var payload = {
      lead_type: leadType,
      organization_name: (data.get("organization_name") || "").toString().trim() || null,
      contact_name: (data.get("contact_name") || data.get("name") || "").toString().trim(),
      work_email: (data.get("work_email") || data.get("email") || "").toString().trim(),
      phone: (data.get("phone") || "").toString().trim() || null,
      organization_type: (data.get("organization_type") || data.get("interest") || "").toString() || null,
      estimated_monthly_rides: (data.get("estimated_monthly_rides") || "").toString() || null,
      service_area: (data.get("service_area") || "").toString().trim() || null,
      transportation_needs: (data.get("transportation_needs") || "").toString().trim() || null,
      preferred_contact_method: (data.get("preferred_contact_method") || "").toString() || null,
      subject: (data.get("subject") || "").toString() || null,
      message: (data.get("message") || "").toString().trim() || null,
      consent: data.get("consent") === "true" || data.get("consent") === "on",
      source_path: window.location.pathname,
      lead_source: "website",
      website: (data.get("website") || "").toString(),
    };
    return payload;
  }

  function validateClient(form, payload) {
    if (!payload.contact_name || payload.contact_name.length < 2) {
      return "Please enter your name.";
    }
    if (!payload.work_email || payload.work_email.indexOf("@") < 1) {
      return "Please enter a valid work email.";
    }
    if (payload.lead_type === "provider_interest") {
      if (!payload.organization_name) return "Please enter your organization name.";
      if (!payload.organization_type) return "Please select an organization type.";
      if (!payload.phone) return "Please enter a phone number.";
      if (!payload.service_area) return "Please enter a service area.";
      if (!payload.preferred_contact_method) return "Please choose a preferred contact method.";
      if (!payload.transportation_needs) return "Please describe your transportation needs.";
      if (!payload.consent) return "Please confirm consent to be contacted.";
    }
    if (payload.lead_type === "contact") {
      if (!payload.subject) return "Please select what you are interested in.";
      if (!payload.message) return "Please enter a message.";
      if (!payload.consent) return "Please confirm consent to be contacted.";
    }
    return "";
  }

  function initForms() {
    document.querySelectorAll("[data-amicor-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var payload = collectPayload(form);
        var clientError = validateClient(form, payload);
        if (clientError) {
          setFormMessage(form, "error", clientError);
          return;
        }

        var submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
          submitBtn.disabled = true;
        }
        setFormMessage(form, "error", "");

        fetch("/api/marketing/leads", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(payload),
        })
          .then(function (response) {
            return response.json().then(function (body) {
              return { response: response, body: body };
            });
          })
          .then(function (result) {
            if (!result.response.ok || (result.body && result.body.ok === false)) {
              var detail =
                (result.body && result.body.error) ||
                (result.body && result.body.detail) ||
                "Unable to submit right now. Please try again.";
              if (Array.isArray(detail)) {
                detail = detail
                  .map(function (item) {
                    return item.msg || JSON.stringify(item);
                  })
                  .join(" ");
              }
              throw new Error(String(detail));
            }
            setFormMessage(
              form,
              "success",
              form.getAttribute("data-success") ||
                "Thank you. AMICOR has received your message and will respond shortly."
            );
            form.reset();
          })
          .catch(function (err) {
            setFormMessage(
              form,
              "error",
              (err && err.message) || "Unable to submit right now. Please try again."
            );
          })
          .finally(function () {
            if (submitBtn) submitBtn.disabled = false;
          });
      });
    });
  }

  function applyIntentDefaults() {
    var params = new URLSearchParams(window.location.search);
    var intent = params.get("intent");
    if (!intent) return;
    var subject = document.querySelector("[name='subject'], [name='interest']");
    if (subject && !subject.value) {
      subject.value = intent;
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initNav();
    initForms();
    applyIntentDefaults();
  });
})();
