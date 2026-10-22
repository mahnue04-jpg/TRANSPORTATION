/* Shared Nova screen-language preference. Account value wins when signed in. */
(function () {
  "use strict";
  var KEY = "amicor_nova_screen_language";
  var supported = ["en", "so", "ar", "fr", "es"];

  function read() {
    try { return localStorage.getItem(KEY) || ""; } catch (_) { return ""; }
  }

  function write(code) {
    if (supported.indexOf(code) < 0) code = "en";
    try { localStorage.setItem(KEY, code); } catch (_) {}
    return code;
  }

  function session() {
    return window.AmiCorSession;
  }

  function token() {
    return session() && session().getAccessToken && session().getAccessToken();
  }

  async function pull() {
    if (!token()) return read();
    var response = await fetch("/api/nova/language", {
      headers: session().getAuthHeaders(),
      cache: "no-store"
    });
    if (!response.ok) return read();
    var body = await response.json();
    if (!body || supported.indexOf(body.screen_language) < 0) return read();
    if (body.voice_interpretation || body.bidirectional_text) return read();
    return write(body.screen_language);
  }

  async function push(code) {
    code = write(code);
    if (!token()) return {screen_language: code, persisted: false, voice_interpretation: false, bidirectional_text: false};
    var headers = {"Content-Type": "application/json"};
    var auth = session().getAuthHeaders();
    Object.keys(auth).forEach(function (name) { headers[name] = auth[name]; });
    var response = await fetch("/api/nova/language", {
      method: "PUT",
      headers: headers,
      body: JSON.stringify({screen_language: code})
    });
    if (!response.ok) return {screen_language: code, persisted: false, voice_interpretation: false, bidirectional_text: false};
    return response.json();
  }

  window.AmiCorLanguage = {
    key: KEY,
    supported: supported,
    workspace: supported,
    read: read,
    write: write,
    pull: pull,
    push: push
  };
})();
