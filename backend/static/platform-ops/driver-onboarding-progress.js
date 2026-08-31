(function () {
  const API = "/api/platform-ops/driver-onboarding";
  const params = new URLSearchParams(window.location.search);
  const appId = params.get("application_id") || localStorage.getItem("driver_onboarding_app") || "";
  const token = params.get("token") || localStorage.getItem("driver_onboarding_token") || "";
  const banner = document.getElementById("banner");
  const overall = document.getElementById("overall-status");
  const nextAction = document.getElementById("next-action");
  const list = document.getElementById("item-list");

  function showBanner(message, ok) {
    banner.textContent = message;
    banner.className = "banner " + (ok ? "ok" : "error");
    banner.classList.remove("hidden");
  }

  function lightClass(light) {
    if (light === "GREEN") return "ok";
    if (light === "YELLOW") return "warn";
    return "error";
  }

  async function load() {
    if (!appId || !token) {
      overall.textContent = "Open this page from your application link, or complete /platform-ops/driver-apply first.";
      return;
    }
    const response = await fetch(API + "/applications/" + appId + "/progress", {
      headers: { "X-Applicant-Token": token },
    });
    const json = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      showBanner(json.detail || "Unable to load progress", false);
      return;
    }
    overall.textContent = "Status: " + (json.overall_status || "—") + " · " + (json.progress_percent || 0) + "% complete";
    nextAction.textContent = "Next: " + (json.next_required_action || "—");
    const apply = "/platform-ops/driver-apply?application_id=" + encodeURIComponent(appId) + "&token=" + encodeURIComponent(token);
    document.querySelector("a[href='/platform-ops/driver-apply']").setAttribute("href", apply);
    list.innerHTML = (json.items || []).map(function (item) {
      return "<div class='meta'>"
        + "<span class='health-pill " + lightClass(item.light) + "'>" + item.light + "</span> "
        + "<strong>" + item.label + "</strong> · " + item.status
        + (item.required === false ? " · optional/not required" : "")
        + (item.missing && item.missing.length ? " · missing: " + item.missing.join(", ") : "")
        + (item.expiration ? " · expires " + item.expiration : "")
        + "</div>";
    }).join("");
  }

  load().catch(function (err) {
    showBanner(err.message || String(err), false);
  });
})();
