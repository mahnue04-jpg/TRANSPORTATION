"use strict";

(function () {
  function $(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function identity() {
    var current = session() && session().getCurrent ? session().getCurrent() : null;
    return current && current.identity ? current.identity : null;
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
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function listHtml(items, empty, render) {
    if (!items || !items.length) return empty;
    return items.map(render).join("");
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
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · Work & Revenue"
      : "Sign in to use the Work & Revenue Engine.";
  }
  function oppItem(row) {
    return "<div class=\"item\"><strong>" + escapeHtml(row.opportunity_title) + "</strong>" +
      "<div class=\"muted\">" + escapeHtml(row.company_name) + " · " + escapeHtml(row.status) +
      (row.qualification_outcome ? " · " + escapeHtml(row.qualification_outcome) : "") +
      "</div></div>";
  }
  function renderDashboard(data, audit) {
    var counts = data.counts || {};
    $("count-opps").textContent = counts.work_opportunities || 0;
    $("count-approvals").textContent = counts.applications_needing_approval || 0;
    $("count-followups").textContent = counts.follow_ups_due || 0;
    $("count-interviews").textContent = counts.interviews || 0;
    $("count-actions").textContent = counts.owner_action_required || 0;
    $("count-won").textContent = counts.work_won || 0;
    $("inbox-list").innerHTML = listHtml(data.opportunity_inbox, "No opportunities in inbox.", oppItem);
    $("qualified-list").innerHTML = listHtml(data.qualified_work, "No qualified work.", oppItem);
    $("app-list").innerHTML = listHtml(data.applications, "No applications.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.application_id) + "</strong>" +
        "<div class=\"muted\">" + escapeHtml(row.approval_state) +
        (row.approved_for_future_submission ? " · APPROVED_FOR_FUTURE_SUBMISSION" : "") +
        "</div></div>";
    });
    $("approval-list").innerHTML = listHtml(data.owner_approvals, "No applications waiting for owner approval.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.application_id) +
        "<div class=\"muted\">" + escapeHtml(row.approval_state) + "</div></div>";
    });
    $("follow-list").innerHTML = listHtml(data.follow_ups, "No follow-ups due.", oppItem);
    $("interview-list").innerHTML = listHtml(data.interviews, "No interviews recorded.", oppItem);
    $("won-list").innerHTML = listHtml(data.won_work, "No won work.", oppItem);
    $("action-list").innerHTML = listHtml(data.owner_actions, "No owner actions.", function (row) {
      return "<div class=\"item\"><span class=\"owner-flag\">" + escapeHtml(row.display_label) +
        "</span> · " + escapeHtml(row.action_type) +
        "<div class=\"muted\">" + escapeHtml(row.explanation) + "</div></div>";
    });
    $("revenue-box").textContent = data.revenue_placeholder || "COMING IN LATER PHASE";
    $("audit-list").innerHTML = listHtml(audit, "No activity yet.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.event_type) +
        "<div class=\"muted\">" + escapeHtml(row.summary) + "</div></div>";
    });
  }
  async function refresh() {
    if (!token()) {
      setSignedIn(false);
      return;
    }
    setSignedIn(true);
    var data = await api("/api/nova/work/dashboard");
    var audit = [];
    try { audit = await api("/api/nova/work/audit"); } catch (_) { audit = []; }
    renderDashboard(data, audit);
  }
  $("opp-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      var amount = $("opp-amount").value;
      var created = await api("/api/nova/work/opportunities", {
        method: "POST",
        body: JSON.stringify({
          company_name: $("opp-company").value,
          opportunity_title: $("opp-title").value,
          location: $("opp-location").value || null,
          remote_status: $("opp-remote").value,
          physical_presence_required: $("opp-physical").value,
          compensation_type: $("opp-comp-type").value || null,
          compensation_amount: amount === "" ? null : Number(amount),
          skills_required: $("opp-skills").value.split(",").map(function (item) { return item.trim(); }).filter(Boolean),
          description: $("opp-desc").value || null,
          requirements: $("opp-req").value || null
        })
      });
      await api("/api/nova/work/opportunities/" + created.opportunity_id + "/qualify", { method: "POST" });
      showBanner("Opportunity saved and qualified. Nothing was submitted externally.", true);
      $("opp-form").reset();
      await refresh();
    } catch (err) { showBanner(err.message); }
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
    await refresh();
    showBanner("Signed in. Work & Revenue Engine is available.", true);
  });
  $("sign-out").addEventListener("click", async function () {
    if (session() && session().logout) await session().logout();
    window.location.href = "/nova/work";
  });
  refresh().catch(function (err) { showBanner(err.message); });
})();
