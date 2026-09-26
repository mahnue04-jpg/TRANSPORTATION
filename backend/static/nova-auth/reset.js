(function () {
  function $(id) { return document.getElementById(id); }
  function show(message, ok) {
    var el = $("banner");
    el.textContent = message;
    el.classList.remove("hidden");
    el.classList.toggle("ok", !!ok);
  }
  function tokenFromQuery() {
    try {
      return new URLSearchParams(window.location.search).get("token") || "";
    } catch (_) {
      return "";
    }
  }
  var token = tokenFromQuery();
  if (!token) {
    show("This reset link is missing or invalid. Request a new password reset.");
  }
  $("reset-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (!token) {
      show("This reset link is missing or invalid. Request a new password reset.");
      return;
    }
    var nextPassword = $("new_password").value;
    var confirmPassword = $("confirm_password").value;
    if (nextPassword !== confirmPassword) {
      show("Passwords do not match.");
      return;
    }
    fetch("/api/auth/reset-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: token,
        new_password: nextPassword,
        confirm_password: confirmPassword
      })
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) throw new Error((body && body.detail) || "Reset failed.");
        show((body.message || "Password updated.") + " You can sign in now.", true);
        window.setTimeout(function () { window.location.href = "/nova"; }, 1200);
      });
    }).catch(function (err) {
      show(err.message || String(err));
    });
  });
})();
