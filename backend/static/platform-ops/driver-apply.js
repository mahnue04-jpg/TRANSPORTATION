(function () {
  const API = "/api/platform-ops/driver-onboarding";
  const params = new URLSearchParams(window.location.search);
  const orgInput = document.getElementById("organization_id");
  const appInput = document.getElementById("application_id");
  const form = document.getElementById("application-form");
  const banner = document.getElementById("banner");
  const successPanel = document.getElementById("success-panel");
  const prevBtn = document.getElementById("prev-step");
  const nextBtn = document.getElementById("next-step");
  const submitBtn = document.getElementById("submit-application");
  const startNewBtn = document.getElementById("start-new-application");
  let applicantToken = localStorage.getItem("driver_onboarding_token") || "";
  let currentStep = 1;
  const TOTAL_STEPS = 5;
  // category -> "name|size" for files already uploaded this session, or "existing|<id>"
  const uploadedSignatures = {};
  let existingApplicationLoaded = false;
  let restoreAttempted = false;
  let lastHydratedApplication = null;

  orgInput.value = params.get("organization_id") || localStorage.getItem("driver_onboarding_org") || "";
  appInput.value = params.get("application_id") || localStorage.getItem("driver_onboarding_app") || "";
  if (params.get("token")) {
    applicantToken = params.get("token");
    localStorage.setItem("driver_onboarding_token", applicantToken);
  }

  const signedDate = form.elements.signed_date;

  function showBanner(message, ok) {
    banner.textContent = message;
    banner.className = "banner " + (ok ? "ok" : "error");
    banner.classList.remove("hidden");
  }

  function clearApplicationSession() {
    localStorage.removeItem("driver_onboarding_app");
    localStorage.removeItem("driver_onboarding_token");
    appInput.value = "";
    applicantToken = "";
    Object.keys(uploadedSignatures).forEach(function (key) { delete uploadedSignatures[key]; });
  }

  function resetFormForNewApplication() {
    form.reset();
    if (signedDate) signedDate.value = new Date().toISOString().slice(0, 10);
    orgInput.value = params.get("organization_id") || localStorage.getItem("driver_onboarding_org") || orgInput.value;
    successPanel.classList.add("hidden");
    form.classList.remove("hidden");
    showStep(1);
    banner.classList.add("hidden");
  }

  function startNewApplication() {
    lastHydratedApplication = null;
    existingApplicationLoaded = false;
    clearApplicationSession();
    resetFormForNewApplication();
    showBanner("Starting a new application. Previous submission was not changed.", true);
  }

  function showStep(step) {
    currentStep = step;
    document.querySelectorAll("[data-step-panel]").forEach(function (panel) {
      panel.classList.toggle("hidden", Number(panel.getAttribute("data-step-panel")) !== step);
    });
    document.querySelectorAll(".step-dot").forEach(function (dot) {
      const n = Number(dot.getAttribute("data-step"));
      dot.classList.toggle("active", n === step);
      dot.classList.toggle("done", n < step);
    });
    prevBtn.classList.toggle("hidden", step === 1);
    nextBtn.classList.toggle("hidden", step === TOTAL_STEPS);
    submitBtn.classList.toggle("hidden", step !== TOTAL_STEPS);
    if (lastHydratedApplication) {
      fillFormFromApplication(lastHydratedApplication, { onlyIfEmpty: true });
    }
  }

  function persistSession() {
    if (orgInput.value) localStorage.setItem("driver_onboarding_org", orgInput.value);
    if (appInput.value) localStorage.setItem("driver_onboarding_app", appInput.value);
    if (applicantToken) localStorage.setItem("driver_onboarding_token", applicantToken);
  }

  function unwrapApplication(payload) {
    if (!payload || typeof payload !== "object") return payload;
    if (payload.id || payload.legal_first_name || payload.email) return payload;
    if (payload.application && typeof payload.application === "object") return payload.application;
    if (payload.data && typeof payload.data === "object") {
      if (payload.data.application) return payload.data.application;
      return payload.data;
    }
    return payload;
  }

  function normalizeDateValue(value) {
    if (value == null || value === "") return "";
    const match = String(value).match(/^(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : String(value);
  }

  function findField(name) {
    if (!form) return null;
    return form.querySelector('[name="' + name + '"]') || (form.elements && form.elements[name]) || null;
  }

  function setFieldValue(name, value, options) {
    const el = findField(name);
    if (!el) return false;
    const onlyIfEmpty = !!(options && options.onlyIfEmpty);
    if (el.type === "checkbox") {
      if (onlyIfEmpty && el.checked) return false;
      el.checked = value === true || value === "true" || value === 1 || value === "1";
      return true;
    }
    if (value == null || value === "") return false;
    if (onlyIfEmpty && String(el.value || "").trim()) return false;
    let next = value;
    if (el.type === "date") next = normalizeDateValue(value);
    else if (el.type === "number") next = String(value);
    el.value = next;
    if ("defaultValue" in el) el.defaultValue = String(next);
    try { el.setAttribute("value", String(next)); } catch (_) { /* date/number inputs still keep .value */ }
    el.setAttribute("autocomplete", "off");
    el.setAttribute("data-hydrated", "1");
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function withPanelsVisible(fn) {
    const hidden = [];
    document.querySelectorAll("[data-step-panel]").forEach(function (panel) {
      if (panel.classList.contains("hidden")) {
        hidden.push(panel);
        panel.classList.remove("hidden");
      }
    });
    try {
      fn();
    } finally {
      hidden.forEach(function (panel) { panel.classList.add("hidden"); });
    }
  }

  function markExistingUploads(documents) {
    const inputByCategory = {
      drivers_license_front: "file_license_front",
      drivers_license_back: "file_license_back",
      vehicle_registration: "file_registration",
      proof_of_auto_insurance: "file_insurance",
      independent_contractor_agreement: "file_contractor",
    };
    (documents || []).forEach(function (doc) {
      if (!doc || String(doc.review_status || "").toLowerCase() === "rejected") return;
      uploadedSignatures[doc.category] = "existing|" + (doc.id || doc.category);
      const input = document.getElementById(inputByCategory[doc.category] || "");
      if (!input || !input.parentElement) return;
      input.removeAttribute("required");
      let hint = input.parentElement.querySelector(".on-file-hint");
      if (!hint) {
        hint = document.createElement("span");
        hint.className = "on-file-hint";
        input.parentElement.appendChild(hint);
      }
      hint.textContent = "Already on file" + (doc.original_filename ? ": " + doc.original_filename : ".");
    });
  }

  function fillFormFromApplication(raw, options) {
    const app = unwrapApplication(raw);
    if (!app) return false;
    const opts = options || {};
    let populated = 0;
    withPanelsVisible(function () {
      orgInput.value = app.organization_id || orgInput.value;
      appInput.value = app.id || appInput.value;
      const mapped = [
        ["legal_first_name", app.legal_first_name],
        ["legal_middle_name", app.legal_middle_name],
        ["legal_last_name", app.legal_last_name],
        ["email", app.email],
        ["mobile_phone", app.mobile_phone],
        ["home_address", app.home_address],
        ["city", app.city],
        ["state", app.state],
        ["zip_code", app.zip_code],
        ["date_of_birth", app.date_of_birth],
        ["emergency_contact_name", app.emergency_contact_name],
        ["emergency_contact_phone", app.emergency_contact_phone],
        ["drivers_license_number", app.drivers_license_number || app.drivers_license_number_masked],
        ["license_issuing_state", app.license_issuing_state],
        ["license_expiration_date", app.license_expiration_date],
        ["vehicle_year", app.vehicle_year],
        ["vehicle_make", app.vehicle_make],
        ["vehicle_model", app.vehicle_model],
        ["vehicle_color", app.vehicle_color],
        ["vehicle_license_plate", app.vehicle_license_plate],
        ["vehicle_plate_state", app.vehicle_plate_state],
        ["vehicle_registration_expiration", app.vehicle_registration_expiration],
        ["vehicle_vin", app.vehicle_vin],
        ["insurance_carrier", app.insurance_carrier],
        ["insurance_policy_number", app.insurance_policy_number || app.insurance_policy_ref_masked],
        ["insurance_effective_date", app.insurance_effective_date],
        ["insurance_expiration_date", app.insurance_expiration_date],
        ["declaration_mvr_authorization", app.declaration_mvr_authorization],
        ["declaration_valid_license", app.declaration_valid_license],
        ["authorize_qualification_checks", app.declaration_background_authorization || app.authorize_qualification_checks],
        ["electronic_signature", app.electronic_signature],
        ["signed_date", app.signed_date],
      ];
      mapped.forEach(function (pair) {
        if (setFieldValue(pair[0], pair[1], opts)) populated += 1;
      });
      if (app.w9_workflow_status) setFieldValue("w9_secure_workflow_started", true, opts);
      markExistingUploads(app.documents);
    });
    persistSession();
    existingApplicationLoaded = true;
    lastHydratedApplication = app;
    return populated > 0 || !!(app.documents && app.documents.length);
  }

  function showSubmittedState(statusLabel) {
    form.classList.add("hidden");
    successPanel.classList.remove("hidden");
    const progressLink = document.getElementById("open-progress");
    if (progressLink && appInput.value && applicantToken) {
      progressLink.setAttribute(
        "href",
        "/platform-ops/driver-onboarding?application_id="
          + encodeURIComponent(appInput.value)
          + "&token=" + encodeURIComponent(applicantToken)
      );
    }
    showBanner("Your existing application is on file. Status: " + (statusLabel || "submitted") + ".", true);
  }

  async function restoreExistingApplication() {
    restoreAttempted = true;
    if (!appInput.value || !applicantToken) {
      if (signedDate && !signedDate.value) {
        signedDate.value = new Date().toISOString().slice(0, 10);
      }
      return false;
    }
    try {
      const app = await api("/applications/" + appInput.value);
      const hydrated = fillFormFromApplication(app);
      setTimeout(function () { fillFormFromApplication(app, { onlyIfEmpty: true }); }, 50);
      setTimeout(function () { fillFormFromApplication(app, { onlyIfEmpty: true }); }, 300);
      const status = String((unwrapApplication(app) && unwrapApplication(app).status) || "").toLowerCase();
      if (status && status !== "draft") {
        showSubmittedState(unwrapApplication(app).status);
        return true;
      }
      if (hydrated) {
        showBanner("Continuing your existing application. Saved information was loaded. Nothing was reset or duplicated.", true);
      } else {
        showBanner("Continuing your existing application. Saved information could not be shown in the form. A new application was not created.", false);
      }
      return true;
    } catch (err) {
      showBanner(
        "Could not open your existing application. Use your original application link. A new application was not created. "
          + (err.message || ""),
        false
      );
      return false;
    }
  }

  function payloadFromForm() {
    const data = new FormData(form);
    const body = {
      organization_id: orgInput.value,
    };
    if (form.elements.preferred_language && form.elements.preferred_language.value) {
      body.preferred_language = form.elements.preferred_language.value;
    } else if (existingApplicationLoaded) {
      // Keep existing language/employment on partial saves; do not invent empty overwrites.
    } else {
      body.preferred_language = "English";
      body.employment_type = "independent_contractor";
    }
    for (const [key, value] of data.entries()) {
      if (key === "organization_id" || key === "application_id") continue;
      if (
        key.startsWith("declaration_") ||
        key === "authorize_qualification_checks" ||
        key === "w9_secure_workflow_started" ||
        key === "payout_setup_started"
      ) {
        const checked = !!(form.elements[key] && form.elements[key].checked);
        if (checked) body[key] = true;
        continue;
      }
      if (key === "vehicle_year") {
        if (value) body[key] = Number(value);
        continue;
      }
      if (existingApplicationLoaded && (value == null || value === "")) continue;
      body[key] = value || null;
    }
    if (body.authorize_qualification_checks) {
      body.declaration_background_authorization = true;
      body.declaration_drug_alcohol_policy = true;
      body.declaration_truthful_information = true;
      if (!body.declaration_valid_license) body.declaration_valid_license = true;
      if (!body.declaration_mvr_authorization) body.declaration_mvr_authorization = true;
    }
    return body;
  }

  async function api(path, options) {
    const headers = Object.assign({ "Content-Type": "application/json" }, (options && options.headers) || {});
    if (applicantToken) headers["X-Applicant-Token"] = applicantToken;
    const response = await fetch(API + path, Object.assign({}, options || {}, { headers: headers }));
    const text = await response.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch (_) { json = { detail: text }; }
    if (!response.ok) {
      const detail = json && json.detail ? json.detail : json;
      if (detail && detail.errors) {
        throw new Error(detail.errors.map(function (e) { return e.message || (e.field + " is required"); }).join("\n"));
      }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return json;
  }

  function isNonDraftError(message) {
    return /only draft applications can be edited/i.test(String(message || ""));
  }

  async function ensureApplication() {
    if (appInput.value) {
      if (!applicantToken) {
        throw new Error(
          "Your existing application could not be opened because the applicant link token is missing. "
            + "A new application was not created. Use your original application link."
        );
      }
      try {
        const app = await api("/applications/" + appInput.value);
        fillFormFromApplication(app);
        const appStatus = String((unwrapApplication(app) && unwrapApplication(app).status) || "").toLowerCase();
        if (appStatus && appStatus !== "draft") {
          showSubmittedState(app.status);
          throw new Error("This application is already " + app.status + " and cannot be edited.");
        }
        return;
      } catch (err) {
        if (isNonDraftError(err.message) || /already/i.test(err.message || "")) {
          throw err;
        }
        throw new Error(
          "Could not open your existing application. A new application was not created. "
            + (err.message || "")
        );
      }
    }

    if (!orgInput.value) {
      throw new Error("Open this page with your Amicor application link (organization required).");
    }

    const created = await api("/applications", { method: "POST", body: JSON.stringify({ organization_id: orgInput.value }) });
    appInput.value = created.application.id;
    applicantToken = created.applicant_access_token;
    persistSession();
    Object.keys(uploadedSignatures).forEach(function (key) { delete uploadedSignatures[key]; });
  }

  function fileSignature(file) {
    return String(file.name || "") + "|" + String(file.size || 0);
  }

  async function uploadIfPresent(inputId, category, required) {
    const input = document.getElementById(inputId);
    if (!input || !input.files || !input.files[0]) {
      if (required && !uploadedSignatures[category]) {
        throw new Error("Please upload the required file for " + category.replace(/_/g, " ") + ".");
      }
      return;
    }
    const file = input.files[0];
    const signature = fileSignature(file);
    if (uploadedSignatures[category] === signature) {
      return;
    }
    const body = new FormData();
    body.append("file", file);
    const headers = {};
    if (applicantToken) headers["X-Applicant-Token"] = applicantToken;
    const response = await fetch(
      API + "/applications/" + appInput.value + "/documents?category=" + encodeURIComponent(category),
      { method: "POST", headers: headers, body: body }
    );
    if (!response.ok) {
      const err = await response.json().catch(function () { return {}; });
      const detail = err && err.detail ? err.detail : null;
      throw new Error(typeof detail === "string" ? detail : ("Upload failed for " + category));
    }
    uploadedSignatures[category] = signature;
  }

  async function uploadStepFiles(requireAll) {
    const requireUploads = !!requireAll || currentStep === TOTAL_STEPS;
    await uploadIfPresent("file_license_front", "drivers_license_front", requireUploads || currentStep === 2);
    await uploadIfPresent("file_license_back", "drivers_license_back", requireUploads || currentStep === 2);
    await uploadIfPresent("file_registration", "vehicle_registration", requireUploads || currentStep === 3);
    await uploadIfPresent("file_insurance", "proof_of_auto_insurance", requireUploads || currentStep === 3);
    await uploadIfPresent("file_contractor", "independent_contractor_agreement", requireUploads || currentStep === 5);
  }

  function validateCurrentStep() {
    const panel = document.querySelector('[data-step-panel="' + currentStep + '"]');
    if (!panel) return true;
    const required = panel.querySelectorAll("input[required], select[required]");
    for (let i = 0; i < required.length; i += 1) {
      const el = required[i];
      if (el.type === "checkbox") {
        if (!el.checked) {
          el.focus();
          throw new Error("Please complete the required checkbox on this step.");
        }
      } else if (el.type === "file") {
        const categoryHint = el.id || "";
        const already =
          (categoryHint.indexOf("license_front") >= 0 && uploadedSignatures.drivers_license_front) ||
          (categoryHint.indexOf("license_back") >= 0 && uploadedSignatures.drivers_license_back) ||
          (categoryHint.indexOf("registration") >= 0 && uploadedSignatures.vehicle_registration) ||
          (categoryHint.indexOf("insurance") >= 0 && uploadedSignatures.proof_of_auto_insurance) ||
          (categoryHint.indexOf("contractor") >= 0 && uploadedSignatures.independent_contractor_agreement);
        if ((!el.files || !el.files[0]) && !already) {
          el.focus();
          throw new Error("Please upload the required document on this step.");
        }
      } else if (!el.value) {
        el.focus();
        throw new Error("Please complete the highlighted fields on this step.");
      }
    }
    if (currentStep === 2 && form.elements.declaration_mvr_authorization && !form.elements.declaration_mvr_authorization.checked) {
      throw new Error("Please authorize driving-record review to continue.");
    }
    if (currentStep === 4) {
      if (!form.elements.authorize_qualification_checks.checked) {
        throw new Error("Please authorize Amicor to run applicable qualification checks.");
      }
      if (!form.elements.declaration_valid_license.checked) {
        throw new Error("Please confirm you hold a valid driver's license.");
      }
    }
    return true;
  }

  document.querySelectorAll(".step-dot").forEach(function (dot) {
    dot.addEventListener("click", function () {
      const target = Number(dot.getAttribute("data-step"));
      if (target < currentStep || existingApplicationLoaded) showStep(target);
    });
  });

  prevBtn.addEventListener("click", function () {
    if (currentStep > 1) showStep(currentStep - 1);
  });

  nextBtn.addEventListener("click", async function () {
    try {
      validateCurrentStep();
      await ensureApplication();
      const savedNext = await api("/applications/" + appInput.value, { method: "PUT", body: JSON.stringify(payloadFromForm()) });
      fillFormFromApplication(savedNext, { onlyIfEmpty: true });
      await uploadStepFiles(false);
      persistSession();
      showStep(currentStep + 1);
    } catch (err) {
      showBanner(err.message || String(err), false);
    }
  });

  document.getElementById("save-draft").addEventListener("click", async function () {
    try {
      await ensureApplication();
      const saved = await api("/applications/" + appInput.value, { method: "PUT", body: JSON.stringify(payloadFromForm()) });
      fillFormFromApplication(saved, { onlyIfEmpty: true });
      await uploadStepFiles(false);
      persistSession();
      showBanner("Draft saved. You can come back anytime. Your existing application was updated, not replaced.", true);
    } catch (err) {
      showBanner(err.message || String(err), false);
    }
  });

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      validateCurrentStep();
      await ensureApplication();
      await api("/applications/" + appInput.value, { method: "PUT", body: JSON.stringify(payloadFromForm()) });
      await uploadStepFiles(true);
      await api("/applications/" + appInput.value + "/submit", {
        method: "POST",
        body: JSON.stringify({ confirmation: true, simple_confirmation_message: true }),
      });
      persistSession();
      showSubmittedState("submitted");
      showBanner("Application submitted. Amicor is reviewing your information.", true);
    } catch (err) {
      showBanner(err.message || String(err), false);
    }
  });

  if (startNewBtn) {
    startNewBtn.addEventListener("click", function () {
      existingApplicationLoaded = false;
      startNewApplication();
    });
  }

  window.addEventListener("pageshow", function () {
    if (lastHydratedApplication) {
      fillFormFromApplication(lastHydratedApplication, { onlyIfEmpty: true });
      return;
    }
    if (appInput.value && applicantToken) restoreExistingApplication();
  });

  showStep(1);
  restoreExistingApplication();
})();
