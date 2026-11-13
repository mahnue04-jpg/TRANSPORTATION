(function () {
  // Never intercept a deliberate sign-in just because an old browser token exists.
  // The login endpoint verifies credentials; cached tokens are not proof of login.
  function setupAuthGuard() {
    if (!window.addEventListener) return;
    window.addEventListener("amicor:session-invalid", function (event) {
      var detail = event && event.detail ? event.detail : {};
      var reason = String(detail.reason || "");
      if (!/401|invalid|expired|access_401/i.test(reason)) return;
      var status = document.getElementById("session-meta");
      if (status) status.textContent = "Session expired or rejected. Sign in again with your Studio staging account.";
      var banner = document.getElementById("banner");
      if (banner) {
        banner.textContent = "Your Studio session is not valid. Please sign in again; the existing projects have not been changed.";
        banner.classList.remove("hidden");
        banner.classList.add("error");
      }
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupAuthGuard, { once: true });
  } else {
    setupAuthGuard();
  }
})();
