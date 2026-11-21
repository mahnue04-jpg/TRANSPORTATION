/* Binds a screen-language control to the shared preference.
   Rollout languages stay a preference. This file does not sign in or translate. */
(function () {
  "use strict";
  var FALLBACK = "If this screen cannot show the selected language, the original text stays in place.";

  function mount(doc, api) {
    doc = doc || document;
    api = api || (typeof window !== "undefined" ? window.AmiCorLanguage : null);
    var select = doc.getElementById("screen-language");
    var notice = doc.getElementById("language-rollout-notice");
    var fallback = doc.getElementById("language-fallback");
    if (fallback) {
      fallback.textContent = FALLBACK;
      fallback.hidden = false;
    }
    if (!select || !api) return {painted: ""};

    function paint(code) {
      var known = api.supported && api.supported.indexOf(code) >= 0;
      var next = known ? code : "en";
      if (select.querySelector('option[value="' + next + '"]')) select.value = next;
      if (api.applyNotice) api.applyNotice(notice, next);
      if (doc.documentElement) {
        doc.documentElement.lang = next;
        doc.documentElement.setAttribute("data-nova-language", next);
      }
      return next;
    }

    var saved = api.read ? api.read() : "";
    var painted = paint(saved || select.value || "en");
    select.addEventListener("change", function () {
      var code = select.value;
      if (api.push) api.push(code);
      painted = paint(code);
    });
    if (api.pull) {
      api.pull().then(function (code) {
        if (code) painted = paint(code);
      }).catch(function () {
        painted = paint(select.value || "en");
      });
    }
    return {painted: painted};
  }

  window.AmiCorLanguageSurface = {mount: mount, fallbackText: FALLBACK};
  if (typeof document !== "undefined" && document.getElementById) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { mount(document); });
    else mount(document);
  }
})();
