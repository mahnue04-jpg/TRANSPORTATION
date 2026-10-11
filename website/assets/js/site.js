(function () {
  var config = window.AMICOR_SITE || {};
  var button = document.querySelector("[data-menu-button]");
  var nav = document.querySelector("[data-nav]");
  if (button && nav) {
    button.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      button.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("open")) {
        nav.classList.remove("open");
        button.setAttribute("aria-expanded", "false");
        button.focus();
      }
    });
    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        nav.classList.remove("open");
        button.setAttribute("aria-expanded", "false");
      });
    });
  }

  var year = document.querySelector("[data-year]");
  if (year) year.textContent = String(new Date().getFullYear());

  var printButton = document.querySelector("[data-print]");
  if (printButton) printButton.addEventListener("click", function () { window.print(); });

  var params = new URLSearchParams(window.location.search);
  var product = document.getElementById("product");
  if (product && params.get("product")) product.value = params.get("product");
  var message = document.querySelector("[name=message]");
  if (message && params.get("intent") === "demo" && !message.value) {
    message.value = "I would like a product demo.";
  }

  if (message && params.get("intent") === "quote" && !message.value) {
    message.placeholder = "Project goal:\nDeliverables needed:\nApproximate volume:\nDeadline:";
  }

  var form = document.querySelector("[data-early-access-form]");
  if (!form) return;

  var planStatus = document.querySelector("[data-plan-status]");
  document.querySelectorAll("[data-plan-choice]").forEach(function (button) {
    button.addEventListener("click", function () {
      var label = button.getAttribute("data-plan-choice") || "";
      form.setAttribute("data-selected-plan", label);
      document.querySelectorAll("[data-plan-choice]").forEach(function (other) {
        other.setAttribute("aria-pressed", other === button ? "true" : "false");
      });
      if (planStatus) planStatus.textContent = "Selected: " + label;
      var productField = form.elements.product;
      if (productField) productField.value = "Nova Operations Agent";
      var formTop = document.getElementById("start-form");
      if (formTop && formTop.scrollIntoView) formTop.scrollIntoView({ block: "start" });
    });
  });

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

  function promptOnly(value) {
    return String(value || "").replace(/\s+/g, " ").trim() === "Project goal: Deliverables needed: Approximate volume: Deadline:";
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    show(success, false);
    show(errorBox, false);
    if (errorBox) errorBox.textContent = "";
    var data = Object.fromEntries(new FormData(form).entries());
    var ok = true;

    if ((data.middle_name_confirm || "").trim()) {
      show(errorBox, true);
      if (errorBox) errorBox.textContent = "Request could not be sent.";
      return;
    }

    ["name", "company", "email", "industry", "companySize", "product", "message"].forEach(function (name) {
      var input = form.elements[name];
      if (!input) return;
      var value = String(data[name] || "").trim();
      if (!value || (name === "message" && promptOnly(value))) {
        setFieldError(input, name === "message" && promptOnly(value)
          ? "Replace the prompts with your project details."
          : "This field is required.");
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

    if (form.hasAttribute("data-start-funnel") && !form.getAttribute("data-selected-plan")) {
      ok = false;
      show(errorBox, true);
      if (errorBox) errorBox.textContent = "Choose a starting option before submitting.";
    }

    if (!ok) {
      show(errorBox, true);
      if (errorBox && !errorBox.textContent) errorBox.textContent = "Please correct the highlighted fields.";
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
      source: "amicor-public-website-w8"
    };
    if (form.hasAttribute("data-start-funnel")) {
      payload.product = "Nova Operations Agent";
    }
    var selectedPlan = form.getAttribute("data-selected-plan") || "";
    if (selectedPlan) {
      payload.message = "Starting option: " + selectedPlan + "\n\n" + payload.message;
    }

    function saveLocal() {
      var submissions = [];
      try {
        submissions = JSON.parse(localStorage.getItem("amicor-early-access") || "[]");
      } catch (err) {
        submissions = [];
      }
      submissions.push(payload);
      try { localStorage.setItem("amicor-early-access", JSON.stringify(submissions)); } catch (err) { /* Storage may be disabled. */ }
    }

    function finishSaved(result) {
      form.reset();
      if (product && params.get("product")) product.value = params.get("product");
      if (message && params.get("intent") === "quote") {
        message.value = "";
        message.placeholder = "Project goal, deliverables, volume, and deadline.";
      }
      show(success, true);
      if (!success) return;
      var ref = String((result && result.referenceId) || "");
      var text = "AMICOR saved your request.";
      if (ref) text += " Reference " + ref + ".";
      if (result && result.duplicate) text += " This matches a request already on file.";
      text += " Email delivery was not confirmed.";
      success.textContent = text;
      if (success.scrollIntoView) success.scrollIntoView({ block: "center" });
      success.focus();
    }

    var endpoint = (config.formEndpoint || "").trim();
    if (!endpoint) {
      saveLocal();
      form.reset();
      if (product && params.get("product")) product.value = params.get("product");
      show(success, true);
      if (success) {
        success.textContent = "Request saved on this device only. It was not sent to AMICOR.";
        success.focus();
      }
      return;
    }

    if (submit) submit.disabled = true;
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (result) {
        if (!response.ok || !result.ok || !result.stored || !result.referenceId) {
          var error = new Error("not_saved");
          error.code = result.error || "not_saved";
          throw error;
        }
        return result;
      });
    }).then(function (result) {
      finishSaved(result);
    }).catch(function (err) {
      saveLocal();
      show(errorBox, true);
      if (errorBox) {
        errorBox.textContent = err && err.code === "message_incomplete"
          ? "Please replace the quote prompts with the project details."
          : "AMICOR did not confirm that this request was saved. Please email info@getamicor.com or try again.";
      }
    }).finally(function () {
      if (submit) submit.disabled = false;
    });
  });
})();
