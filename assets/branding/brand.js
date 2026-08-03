(function (global) {
  "use strict";

  var BRAND = {
    name: "AMICOR",
    productName: "AMICOR",
    assistantName: "Amicor Nova",
    tagline: "Transport. Care. Connect.",
    logoSrc: "/static/branding/amicor-mark.png",
    logoFullSrc: "/static/branding/amicor-logo-full.png",
    logoPngSrc: "/static/branding/amicor-logo-primary.png",
    themeColor: "#0b6bcb",
    accentColor: "#32CD32",
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

  function brandFullHtml(className, alt) {
    var cls = className || "amicor-logo-full";
    return (
      '<img class="' +
      cls +
      '" src="' +
      BRAND.logoFullSrc +
      '" alt="' +
      escapeAttr(alt || BRAND.name + " — " + BRAND.tagline) +
      '" decoding="async" />'
    );
  }

  function surfaceBrandHtml(tagline) {
    var line = tagline == null ? BRAND.tagline : tagline;
    return (
      '<div class="amicor-surface-brand">' +
      brandMarkHtml("amicor-logo amicor-logo-lg") +
      "<div><strong>" +
      escapeAttr(BRAND.name) +
      "</strong>" +
      (line ? '<p class="muted amicor-brand-tagline">' + escapeAttr(line) + "</p>" : "") +
      "</div></div>"
    );
  }

  global.AMICOR_BRAND = BRAND;
  global.amicorBrandMarkHtml = brandMarkHtml;
  global.amicorBrandFullHtml = brandFullHtml;
  global.amicorSurfaceBrandHtml = surfaceBrandHtml;
})(typeof window !== "undefined" ? window : globalThis);
