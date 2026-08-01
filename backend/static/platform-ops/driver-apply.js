(function () {
  const API = "/api/platform-ops/driver-onboarding";
  const params = new URLSearchParams(window.location.search);
  const orgInput = document.getElementById("organization_id");
  const appInput = document.getElementById("application_id");
  const form = document.getElementById("application-form");
  const banner = document.getElementById("banner");
  let applicantToken = localStorage.getItem("driver_onboarding_token") || "";

  orgInput.value = params.get("organization_id") || localStorage.getItem("driver_onboarding_org") || "";
  appInput.value = params.get("application_id") || localStorage.getItem("driver_onboarding_app") || "";

  function showBanner(message, ok) {
    banner.textContent = message;
    banner.className = "banner " + (ok ? "ok" : "error");
    banner.classList.remove("hidden");
  }

  function selectedDays() {
    return Array.from(document.querySelectorAll("#availability_days input:checked")).map((el) => el.value);
  }

  function payloadFromForm() {
    const data = new FormData(form);
    const body = {
      organization_id: orgInput.value,
      availability_days: selectedDays(),
    };
    for (const [key, value] of data.entries()) {
      if (key === "organization_id" || key === "application_id") continue;
      if (key.startsWith("declaration_")) {
        body[key] = form.elements[key].checked;
        continue;
      }
      if (key === "willing_weekends" || key === "willing_wheelchair") {
        body[key] = value === "true" ? true : value === "false" ? false : null;
        continue;
      }
      if (key === "years_driving_experience") {
        body[key] = value ? Number(value) : null;
        continue;
      }
      body[key] = value || null;
    }
    return body;
  }

  async function api(path, options) {
    const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    if (applicantToken) headers["X-Applicant-Token"] = applicantToken;
    const response = await fetch(API + path, Object.assign({}, options, { headers }));
    const text = await response.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch (_) { json = { detail: text }; }
    if (!response.ok) {
      const detail = json && json.detail ? json.detail : json;
      if (detail && detail.errors) {
        const lines = detail.errors.map((e) => `${e.field}: ${e.message}`);
        throw new Error(lines.join("\n"));
      }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return json;
  }

  async function ensureApplication() {
    if (appInput.value && applicantToken) return;
    if (!orgInput.value) throw new Error("organization_id query parameter is required.");
    const created = await api("/applications", { method: "POST", body: JSON.stringify({ organization_id: orgInput.value }) });
    appInput.value = created.application.id;
    applicantToken = created.applicant_access_token;
    localStorage.setItem("driver_onboarding_app", appInput.value);
    localStorage.setItem("driver_onboarding_org", orgInput.value);
    localStorage.setItem("driver_onboarding_token", applicantToken);
  }

  document.getElementById("save-draft").addEventListener("click", async () => {
    try {
      await ensureApplication();
      await api(`/applications/${appInput.value}`, { method: "PUT", body: JSON.stringify(payloadFromForm()) });
      showBanner("Draft saved.", true);
    } catch (err) {
      showBanner(err.message || String(err), false);
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await ensureApplication();
      await api(`/applications/${appInput.value}`, { method: "PUT", body: JSON.stringify(payloadFromForm()) });
      const submitted = await api(`/applications/${appInput.value}/submit`, { method: "POST", body: JSON.stringify({ confirmation: true }) });
      showBanner(`Application submitted. Status: ${submitted.status}`, true);
    } catch (err) {
      showBanner(err.message || String(err), false);
    }
  });
})();
