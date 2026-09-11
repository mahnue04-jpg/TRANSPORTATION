(function () {
  var config = window.AMICOR_SITE || {};
  var button = document.querySelector("[data-menu-button]");
  var nav = document.querySelector("[data-nav]");
  if (button && nav) {
    button.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      button.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  var year = document.querySelector("[data-year]");
  if (year) year.textContent = String(new Date().getFullYear());

  var params = new URLSearchParams(window.location.search);
  var product = document.getElementById("product");
  if (product && params.get("product")) product.value = params.get("product");
  var message = document.querySelector("[name=message]");
  if (message && params.get("intent") === "demo" && !message.value) {
    message.value = "I would like a product demo.";
  }

  var form = document.querySelector("[data-early-access-form]");
  if (!form) return;

  var success = document.querySelector("[data-form-success]");
  var errorBox = document.querySelector("[data-form-error]");
  var submit = form.querySelector("[type=submit]");

  function show(el, on) {
    if (!el) return;
    el.classList.toggle("show", !!on);
  }

  function setFieldError(input, text) {
    var host = input.closest("label") || input.parentElement;
    var existing = host.querySelector(".field-error");
    if (!text) {
      if (existing) existing.remove();
      input.removeAttribute("aria-invalid");
      return;
    }
    if (!existing) {
      existing = document.createElement("span");
      existing.className = "field-error";
      host.appendChild(existing);
    }
    existing.textContent = text;
    input.setAttribute("aria-invalid", "true");
  }

  function validEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    show(success, false);
    show(errorBox, false);
    var data = Object.fromEntries(new FormData(form).entries());
    var ok = true;

    if ((data.company_website || "").trim()) {
      show(errorBox, true);
      if (errorBox) errorBox.textContent = "Request could not be sent.";
      return;
    }

    ["name", "company", "email", "industry", "companySize", "product", "message"].forEach(function (name) {
      var input = form.elements[name];
      if (!input) return;
      var value = String(data[name] || "").trim();
      if (!value) {
        setFieldError(input, "This field is required.");
        ok = false;
      } else if (name === "email" && !validEmail(value)) {
        setFieldError(input, "Enter a valid email address.");
        ok = false;
      } else {
        setFieldError(input, "");
      }
    });

    var consent = form.elements.consent;
    if (consent && !consent.checked) {
      setFieldError(consent, "Consent is required to submit this request.");
      ok = false;
    } else if (consent) {
      setFieldError(consent, "");
    }

    if (!ok) {
      show(errorBox, true);
      if (errorBox) errorBox.textContent = "Please correct the highlighted fields.";
      return;
    }

    var payload = {
      receivedAt: new Date().toISOString(),
      name: data.name.trim(),
      company: data.company.trim(),
      email: data.email.trim(),
      phone: (data.phone || "").trim(),
      industry: data.industry.trim(),
      companySize: data.companySize,
      product: data.product,
      message: data.message.trim(),
      consent: true,
      source: "amicor-public-website-w4"
    };

    function saveLocal() {
      var submissions = [];
      try {
        submissions = JSON.parse(localStorage.getItem("amicor-early-access") || "[]");
      } catch (err) {
        submissions = [];
      }
      submissions.push(payload);
      localStorage.setItem("amicor-early-access", JSON.stringify(submissions));
    }

    function finish(localOnly) {
      saveLocal();
      form.reset();
      if (product && params.get("product")) product.value = params.get("product");
      show(success, true);
      if (success) {
        success.textContent = localOnly
          ? "Request saved on this device. No email was sent because a live form endpoint is not configured."
          : "Request received. AMICOR will follow up through the configured intake channel.";
        success.focus();
      }
    }

    var endpoint = (config.formEndpoint || "").trim();
    if (!endpoint) {
      finish(true);
      return;
    }

    if (submit) submit.disabled = true;
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (response) {
      if (!response.ok) throw new Error("endpoint");
      finish(false);
    }).catch(function () {
      saveLocal();
      show(errorBox, true);
      if (errorBox) {
        errorBox.textContent = "The live intake channel was unavailable. Your request was saved on this device as a fallback.";
      }
    }).finally(function () {
      if (submit) submit.disabled = false;
    });
  });
})();
