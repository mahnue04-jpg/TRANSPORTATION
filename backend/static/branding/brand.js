(function (global) {
  "use strict";

  var BRAND = {
    name: "Amicor",
    productName: "Amicor Health ISF",
    logoSrc: "/static/branding/amicor-logo-v1.svg",
    logoPngSrc: "/static/branding/amicor-logo-v1.png",
    themeColor: "#0b6bcb",
    accentColor: "#19c7ff",
  };

  function escapeAttr(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function brandMarkHtml(className, alt) {
    var cls = className || "amicor-logo";
    return (
      '<img class="' +
      cls +
      '" src="' +
      BRAND.logoSrc +
      '" alt="' +
      escapeAttr(alt || BRAND.name) +
      '" width="32" height="32" decoding="async" />'
    );
  }

  function surfaceBrandHtml(tagline) {
    return (
      '<div class="amicor-surface-brand">' +
      brandMarkHtml("amicor-logo amicor-logo-lg") +
      "<div><strong>" +
      escapeAttr(BRAND.name) +
      "</strong>" +
      (tagline ? '<p class="muted">' + escapeAttr(tagline) + "</p>" : "") +
      "</div></div>"
    );
  }

  global.AMICOR_BRAND = BRAND;
  global.amicorBrandMarkHtml = brandMarkHtml;
  global.amicorSurfaceBrandHtml = surfaceBrandHtml;
})(typeof window !== "undefined" ? window : globalThis);
