(function () {
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

  var form = document.querySelector("[data-early-access-form]");
  if (!form) return;

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var data = Object.fromEntries(new FormData(form).entries());
    var submissions = [];
    try {
      submissions = JSON.parse(localStorage.getItem("amicor-early-access") || "[]");
    } catch (err) {
      submissions = [];
    }
    submissions.push({
      receivedAt: new Date().toISOString(),
      name: data.name || "",
      company: data.company || "",
      email: data.email || "",
      phone: data.phone || "",
      industry: data.industry || "",
      companySize: data.companySize || "",
      product: data.product || "",
      message: data.message || "",
    });
    localStorage.setItem("amicor-early-access", JSON.stringify(submissions));
    form.reset();
    var success = document.querySelector("[data-form-success]");
    if (success) {
      success.classList.add("show");
      success.focus();
    }
  });
})();