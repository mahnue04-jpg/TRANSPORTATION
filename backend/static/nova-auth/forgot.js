(function () {
  function $(id) { return document.getElementById(id); }
  function show(message, ok) {
    var el = $("banner");
    el.textContent = message;
    el.classList.remove("hidden");
    el.classList.toggle("ok", !!ok);
  }
  $("forgot-form").addEventListener("submit", function (event) {
    event.preventDefault();
    fetch("/api/auth/forgot-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: $("email").value.trim() })
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) throw new Error((body && body.detail) || "Request failed.");
        show(body.message || "If an account exists for that email, password reset instructions have been sent.", true);
      });
    }).catch(function (err) {
      show(err.message || String(err));
    });
  });
})();
