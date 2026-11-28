"use strict";
(function () {
  function el(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function status(message) { el("status").textContent = message; }

  function signedIn(on) {
    el("storage-probe").disabled = !on;
    el("login-form").hidden = on;
  }

  async function boot() {
    if (session() && session().restore) session().restore();
    signedIn(!!token());
    status(token() ? "Owner controls are available. The storage test has not run." : "Sign in with the owner account.");
  }

  el("login-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    status("Checking owner access…");
    var response = await fetch("/api/auth/login", {
      method: "POST",
      headers: {"Content-Type": "application/json", "Accept": "application/json"},
      body: JSON.stringify({email: el("login-email").value, password: el("login-password").value})
    });
    var payload = null;
    try { payload = await response.json(); } catch (err) { payload = null; }
    if (!response.ok || !payload || !payload.access_token) {
      signedIn(false);
      status("Sign-in was not accepted.");
      return;
    }
    if (session() && session().start) {
      session().start({
        userId: payload.user_id,
        email: payload.email,
        name: payload.display_name,
        role: payload.role,
        accessToken: payload.access_token,
        refreshToken: payload.refresh_token,
        organizationId: payload.organization_id,
        organization_name: payload.organization_name,
        authorizedRoles: payload.authorized_roles
      });
    }
    el("login-password").value = "";
    signedIn(true);
    status("Owner controls are available. The storage test has not run.");
  });

  el("storage-probe").addEventListener("click", async function () {
    if (!token()) {
      status("Sign in with the owner account.");
      return;
    }
    var button = el("storage-probe");
    button.disabled = true;
    status("Running the private storage round trip…");
    el("probe-result").textContent = "";
    try {
      var headers = {"Accept": "application/json", "X-Nova-Owner-Action": "run-synthetic-storage-probe"};
      if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
      headers["X-Nova-Owner-Action"] = "run-synthetic-storage-probe";
      var response = await fetch("/api/nova/work/operations/owner/storage-probe", {
        method: "POST", cache: "no-store", credentials: "same-origin", headers: headers
      });
      if (response.status === 403) {
        status("Owner access is required.");
        return;
      }
      if (!response.ok) {
        status("Storage probe is unavailable.");
        return;
      }
      var report = await response.json();
      var lines = ["ok", "uploaded", "retrieved", "verified", "deleted", "absent_after_delete", "synthetic"].map(function (name) {
        return name + ": " + (report[name] === true ? "yes" : "no");
      });
      el("probe-result").textContent = lines.join("\n");
      status(report.ok === true ? "Private storage round trip passed." : "Private storage round trip did not pass.");
    } catch (err) {
      status("Storage probe is unavailable.");
    } finally {
      button.disabled = !token();
    }
  });

  boot();
})();
