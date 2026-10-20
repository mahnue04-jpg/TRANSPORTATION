(function () {
  function showBannerMessage(message) {
    var banner = document.getElementById("banner");
    if (!banner) return;
    banner.textContent = message;
    banner.classList.remove("hidden");
    banner.classList.add("error");
  }

  function hasServerSession() {
    try {
      var identityRaw = localStorage.getItem("amicor_identity");
      if (identityRaw) {
        var parsed = JSON.parse(identityRaw);
        if (parsed && (parsed.accessToken || parsed.access_token)) return true;
      }
    } catch (_) {}
    try {
      if (window.AmiCorSession && typeof window.AmiCorSession.getAccessToken === "function") {
        return !!window.AmiCorSession.getAccessToken();
      }
    } catch (_) {}
    return false;
  }

  function guardLoginFormSubmit(event) {
    if (!event || !event.target || event.target.id !== "login-form") return;
    if (!hasServerSession()) return;
    event.preventDefault();
    showBannerMessage(
      "Nova rejected these sign-in credentials (401). Main Nova sign-in may use a different session; check this server account without creating a second casting password."
    );
    return false;
  }

  function setupAuthGuard() {
    var form = document.getElementById("login-form");
    if (form && !form.__amicor_guard_installed) {
      form.__amicor_guard_installed = true;
      form.addEventListener("submit", guardLoginFormSubmit, true);
    }

    if (window.addEventListener) {
      window.addEventListener("amicor:session-invalid", function (event) {
        var detail = event && event.detail ? event.detail : {};
        var reason = String(detail.reason || "");
        if (reason.indexOf("401") !== -1 || reason.indexOf("invalid") !== -1 || reason.indexOf("access_401") !== -1) {
          showBannerMessage(
            "Nova rejected these sign-in credentials (401). Main Nova sign-in may use a different session; check this server account without creating a second casting password."
          );
        }
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupAuthGuard, { once: true });
  } else {
    setupAuthGuard();
  }
})();
