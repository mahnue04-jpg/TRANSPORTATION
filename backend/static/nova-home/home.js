"use strict";

(function () {
  function $(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function identity() {
    var current = session() && session().getCurrent ? session().getCurrent() : null;
    return current && current.identity ? current.identity : null;
  }
  function greeting() {
    var hour = new Date().getHours();
    var part = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening";
    return "Good " + part + ". Let's make today count.";
  }
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function organizationId() {
    return session() && session().getOrganizationId ? session().getOrganizationId() : null;
  }
  function showBanner(message, ok) {
    var el = $("banner");
    el.textContent = message;
    el.classList.remove("hidden");
    el.classList.toggle("ok", !!ok);
  }
  function errorText(payload, fallback) {
    if (!payload) return fallback;
    if (typeof payload.detail === "string") return payload.detail;
    return fallback;
  }
  async function api(path, options) {
    var headers = { "Content-Type": "application/json" };
    if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
    else if (token()) headers.Authorization = "Bearer " + token();
    var response = await fetch(path, Object.assign({}, options || {}, { headers: headers }));
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (response.status === 401) throw new Error("Session expired. Sign in to continue.");
    if (!response.ok) throw new Error(errorText(body, "Request failed (" + response.status + ")"));
    return body;
  }
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
    $("login-form").classList.add("hidden");
    var ident = identity();
    $("session-meta").textContent = on
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · Mrs. Nova Brain"
      : "Sign in to ask Mrs. Nova Brain.";
  }
  async function refreshBrain() {
    if (!token()) {
      $("brain-output").textContent = "Mrs. Nova Brain is ready when you are signed in.";
      setSignedIn(false);
      return;
    }
    setSignedIn(true);
    try {
      var orgId = organizationId();
      var statusPath = "/api/nova/status" + (orgId ? ("?organization_id=" + encodeURIComponent(String(orgId))) : "");
      var status = await api(statusPath);
      $("brain-output").textContent = "Mrs. Nova Brain is connected.\n" +
        (status.next_recommended_action || status.status || "Ready.");
    } catch (err) {
      $("brain-output").textContent = err.message;
    }
  }
  async function askBrain(question) {
    if (!token()) {
      showBanner("Sign in to ask Mrs. Nova Brain.");
      $("login-form").classList.remove("hidden");
      return;
    }
    var body = { question: question, mode: "founder_advisor" };
    var orgId = organizationId();
    if (orgId) body.organization_id = String(orgId);
    var result = await api("/api/nova/ask", {
      method: "POST",
      body: JSON.stringify(body)
    });
    $("brain-output").textContent = result.answer || "No response from Mrs. Nova Brain.";
    showBanner("Mrs. Nova Brain answered using existing Nova intelligence APIs.", true);
  }
  function renderSearch(data) {
    var sources = (data && data.sources) || [];
    var response = data && data.response ? String(data.response) : "";
    var html = "";
    if (response) html += "<p>" + escapeHtml(response) + "</p>";
    html += sources.slice(0, 8).map(function (row) {
      var title = escapeHtml(row.title || row.name || "Result");
      var url = escapeHtml(row.url || row.link || "");
      return "<article><strong>" + title + "</strong>" +
        (url ? "<br /><a href=\"" + url + "\" target=\"_blank\" rel=\"noopener\">" + url + "</a>" : "") +
        "</article>";
    }).join("");
    if (data && (data.status === "degraded" || data.status === "partial")) {
      html += "<p>Live web/news may be incomplete. Existing /api/search was used; no new search engine was added.</p>";
    }
    $("search-results").innerHTML = html || escapeHtml(JSON.stringify(data || { message: "No results" }, null, 2));
  }
  async function runSearch(news) {
    var query = $("command-input").value.trim();
    if (!query) {
      showBanner("Enter a search for the existing web/news capability.");
      return;
    }
    var path = "/api/search?query=" + encodeURIComponent(query) + (news ? "&news_mode=true" : "");
    var data = await api(path);
    renderSearch(data);
    window.location.hash = "web-search";
    showBanner(news ? "News search used existing /api/search." : "Web search used existing /api/search.", true);
  }
  $("boot-greeting").textContent = greeting();
  $("home-greeting").textContent = greeting();
  window.setTimeout(function () { $("boot-screen").classList.add("is-done"); }, 700);

  if (session() && session().restore) session().restore();
  refreshBrain();

  $("command-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var question = $("command-input").value.trim();
    if (question.length < 3) {
      showBanner("Ask Mrs. Nova Brain at least 3 characters, or use Search the web.");
      return;
    }
    try { await askBrain(question); } catch (err) { showBanner(err.message); }
  });
  $("search-web").addEventListener("click", async function () {
    try { await runSearch(false); } catch (err) { showBanner(err.message); }
  });
  $("search-news").addEventListener("click", async function () {
    try { await runSearch(true); } catch (err) { showBanner(err.message); }
  });
  $("sign-in-toggle").addEventListener("click", function () {
    $("login-form").classList.toggle("hidden");
  });
  $("login-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: $("login-email").value, password: $("login-password").value })
    });
    var payload = await response.json();
    if (!response.ok) {
      showBanner(errorText(payload, "Sign-in failed"));
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
    await refreshBrain();
    showBanner("Signed in. Mrs. Nova Brain is available.", true);
  });
  $("sign-out").addEventListener("click", async function () {
    if (session() && session().logout) await session().logout();
    window.location.href = "/nova";
  });
})();
