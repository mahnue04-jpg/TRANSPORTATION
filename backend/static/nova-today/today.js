"use strict";

(function () {
  function $(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function identity() {
    var current = session() && session().getCurrent ? session().getCurrent() : null;
    return current && current.identity ? current.identity : null;
  }
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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
    var response;
    try {
      response = await fetch(path, Object.assign({}, options || {}, { headers: headers }));
    } catch (_) {
      throw new Error("Network error. Saved work was not changed.");
    }
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (response.status === 401) throw new Error("Session expired. Sign in again.");
    if (response.status === 403) throw new Error("Access denied.");
    if (response.status === 404) throw new Error("Not found / unavailable.");
    if (response.status >= 500) throw new Error("Temporary system error.");
    if (!response.ok) throw new Error(errorText(body, "Request failed."));
    return body;
  }
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
    $("login-form").classList.add("hidden");
    var ident = identity();
    $("session-meta").textContent = on
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · Mrs. Nova Brain"
      : "Sign in to use Nova Today.";
  }
  function cardHtml(card) {
    var actions = "";
    if (card.action_id && card.status === "proposed") {
      actions =
        "<div class=\"card-actions\">" +
        "<button type=\"button\" data-approve=\"" + escapeHtml(card.action_id) + "\">Approve</button>" +
        "<button type=\"button\" class=\"secondary\" data-dismiss=\"" + escapeHtml(card.action_id) + "\">Dismiss</button>" +
        "<a class=\"secondary\" href=\"" + escapeHtml(card.href || "/nova/today") + "\">Open</a>" +
        "</div>";
    } else {
      actions = "<div class=\"card-actions\"><a class=\"secondary\" href=\"" + escapeHtml(card.href || "/nova/today") + "\">Open</a></div>";
    }
    return "<article class=\"item\">" +
      "<span class=\"trust\">" + escapeHtml(card.trust_label) + "</span>" +
      "<strong>" + escapeHtml(card.title) + "</strong>" +
      "<div class=\"hint\">" + escapeHtml(card.detail || card.recommended_action) + "</div>" +
      actions +
      "</article>";
  }
  function queueHtml(row) {
    return "<article class=\"item\">" +
      "<span class=\"trust\">ACTION REQUIRES APPROVAL</span>" +
      "<strong>" + escapeHtml(row.title) + "</strong>" +
      "<div class=\"hint\">" + escapeHtml(row.recommended_action) + " · " + escapeHtml(row.source_module) + "</div>" +
      "<div class=\"card-actions\">" +
      "<button type=\"button\" data-approve=\"" + escapeHtml(row.action_id) + "\">Approve</button>" +
      "<button type=\"button\" class=\"secondary\" data-dismiss=\"" + escapeHtml(row.action_id) + "\">Dismiss</button>" +
      "</div></article>";
  }
  function renderList(id, items, empty) {
    if (!items || !items.length) {
      $(id).innerHTML = empty;
      return;
    }
    $(id).innerHTML = items.map(cardHtml).join("");
  }
  async function refresh() {
    if (!token()) {
      $("brain-output").textContent = "Mrs. Nova Brain is ready when you are signed in.";
      setSignedIn(false);
      return;
    }
    var dash = await api("/api/nova/today/dashboard");
    setSignedIn(true);
    renderList("attention-box", dash.attention_now, "Nothing needs attention now.");
    renderList("communications-box", dash.communications, "No communications attention items.");
    renderList("government-box", dash.government, "No government deadlines or grants.");
    renderList("business-box", dash.business, "No business follow-ups or opportunities.");
    renderList("workspace-box", dash.workspace, "No recent workspace work.");
    renderList("links-box", dash.product_links, "Product links unavailable.");
    renderList("recommendations-box", dash.recommendations, "No recommendations.");
    $("queue-box").innerHTML = (dash.approval_queue && dash.approval_queue.length)
      ? dash.approval_queue.map(queueHtml).join("")
      : "No items waiting for approval.";
  }
  async function runBrain(event) {
    event.preventDefault();
    if (!token()) {
      showBanner("Sign in to ask Mrs. Nova Brain.");
      $("login-form").classList.remove("hidden");
      return;
    }
    var result = await api("/api/nova/today/ask", {
      method: "POST",
      body: JSON.stringify({ question: $("ask-input").value.trim() })
    });
    $("brain-output").textContent = (result.fact_label || "AI SUGGESTION") + "\n\n" + (result.answer || "No response from Mrs. Nova Brain.");
    showBanner("Mrs. Nova Brain used existing Nova intelligence. Nothing was sent or filed.", true);
  }
  async function decide(actionId, kind) {
    var path = kind === "approve"
      ? "/api/nova/today/actions/" + encodeURIComponent(actionId) + "/approve"
      : "/api/nova/today/actions/" + encodeURIComponent(actionId) + "/dismiss";
    var result = await api(path, { method: "POST", body: "{}" });
    if (kind === "approve" && result.href) {
      showBanner((result.message || "Approved.") + " Opened only after your confirmation.", true);
    } else {
      showBanner(result.message || "Saved. Refresh will keep this decision.", true);
    }
    await refresh();
  }
  document.addEventListener("click", function (event) {
    var approve = event.target && event.target.getAttribute && event.target.getAttribute("data-approve");
    var dismiss = event.target && event.target.getAttribute && event.target.getAttribute("data-dismiss");
    if (approve) {
      decide(approve, "approve").catch(function (err) { showBanner(err.message || String(err)); });
    }
    if (dismiss) {
      decide(dismiss, "dismiss").catch(function (err) { showBanner(err.message || String(err)); });
    }
  });
  $("ask-form").addEventListener("submit", function (event) {
    runBrain(event).catch(function (err) { showBanner(err.message || String(err)); });
  });
  $("sign-in-toggle").addEventListener("click", function () {
    $("login-form").classList.toggle("hidden");
  });
  $("sign-out").addEventListener("click", function () {
    if (session() && session().logout) {
      session().logout();
    }
    setSignedIn(false);
    showBanner("Signed out.", true);
  });
  $("login-form").addEventListener("submit", function (event) {
    event.preventDefault();
    api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: $("login-email").value.trim(),
        password: $("login-password").value
      })
    }).then(function (payload) {
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
      return refresh();
    }).then(function () {
      showBanner("Signed in. Mrs. Nova Brain is available.", true);
    }).catch(function (err) {
      showBanner(err.message || String(err));
    });
  });
  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message || String(err)); });
})();
