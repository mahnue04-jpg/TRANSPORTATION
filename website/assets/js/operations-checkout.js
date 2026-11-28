(function () {
  "use strict";
  var APP_ORIGIN = "https://amicor-health-isf-py.onrender.com";
  var PACKAGES = {
    starter: true,
    starter_49: true,
    launch_99: true,
    business_299: true
  };

  document.querySelectorAll("[data-operations-package]").forEach(function (link) {
    var key = link.getAttribute("data-operations-package") || "";
    if (!PACKAGES[key]) return;
    var target = APP_ORIGIN + "/nova/operations/customer?signin=1&operations_package=" + encodeURIComponent(key);
    link.setAttribute("data-operations-sales", "disabled");
    link.setAttribute("href", target);
    link.addEventListener("click", function (event) {
      var next;
      try {
        next = new URL(link.getAttribute("href") || "", window.location.href);
      } catch (err) {
        event.preventDefault();
        return;
      }
      var allowed = next.origin === APP_ORIGIN
        && next.pathname === "/nova/operations/customer"
        && next.searchParams.get("signin") === "1"
        && next.searchParams.get("operations_package") === key;
      if (!allowed || link.getAttribute("data-operations-sales") !== "disabled") {
        event.preventDefault();
      }
    });
  });
})();
