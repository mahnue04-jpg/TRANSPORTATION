"use strict";

(function () {
  var activeFilter = "";
  var selectedOpportunityId = "";
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
  function actionButton(action, id, label) {
    return "<button type=\"button\" class=\"secondary\" data-work-action=\"" +
      escapeHtml(action) + "\" data-id=\"" + escapeHtml(id) + "\">" +
      escapeHtml(label) + "</button>";
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
  function approvalLabel(row) {
    if (row.manual_submission_recorded) return "submitted externally (manual record only)";
    if (row.approved_for_future_submission) return "approved for future submission";
    if (row.approval_state === "READY_FOR_OWNER_REVIEW") return "ready for review";
    if (row.approval_state === "REJECTED") return "closed/rejected";
    if (row.approval_state === "NEEDS_CHANGES") return "needs changes";
    if (row.approval_state === "DRAFT") return "draft only";
    return row.approval_state || "none";
  }
  function applicationActions(row) {
    var bits = [];
    if (row.approval_state === "DRAFT" || row.approval_state === "NEEDS_CHANGES") {
      bits.push(actionButton("ready", row.application_id, "Send for owner review"));
    }
    if (row.approval_state === "READY_FOR_OWNER_REVIEW") {
      bits.push(actionButton("approve", row.application_id, "Approve for future submission"));
      bits.push(actionButton("reject", row.application_id, "Reject"));
      bits.push(actionButton("needs-changes", row.application_id, "Request changes"));
    }
    if (row.approved_for_future_submission && !row.manual_submission_recorded) {
      bits.push(actionButton("record-manual", row.application_id, "Record manual submission (Nova will not send)"));
    }
    if (!bits.length) return "";
    return "<div class=\"action-row\">" + bits.join("") + "</div>";
  }
  function oppItem(row) {
    return "<div class=\"item\" data-opportunity-id=\"" + escapeHtml(row.opportunity_id) + "\">" +
      "<strong>" + escapeHtml(row.opportunity_title) + "</strong>" +
      "<div class=\"muted\">" + escapeHtml(row.company_name) +
      " · source " + escapeHtml(row.source || row.source_type) +
      " · " + escapeHtml(row.status) +
      (row.qualification_outcome ? " · " + escapeHtml(row.qualification_outcome) : "") +
      (row.lifecycle_outcome ? " · " + escapeHtml(row.lifecycle_outcome) : "") +
      (row.owner_action_required ? " · OWNER ACTION REQUIRED" : "") +
      (row.application_state ? " · application " + escapeHtml(row.application_state) : "") +
      (row.updated_at ? " · updated " + escapeHtml(row.updated_at) : "") +
      "</div></div>";
  }
  function applicationItem(row) {
    return "<div class=\"item\" data-opportunity-id=\"" + escapeHtml(row.opportunity_id) + "\">" +
      "<strong>" + escapeHtml(row.opportunity_title || row.application_id) + "</strong>" +
      "<div class=\"muted\">" + escapeHtml(approvalLabel(row)) +
      " · " + escapeHtml(row.application_id) + "</div>" +
      applicationActions(row) + "</div>";
  }
  function markActiveFilter() {
    var buttons = document.querySelectorAll("#filter-row [data-filter]");
    buttons.forEach(function (button) {
      button.classList.toggle("filter-on", (button.getAttribute("data-filter") || "") === activeFilter);
    });
  }
  function renderDashboard(data, audit) {
    var counts = data.counts || {};
    $("count-opps").textContent = counts.opportunities_found || counts.work_opportunities || 0;
    $("count-qualified").textContent = counts.qualified || 0;
    $("count-owner-input").textContent = counts.needs_owner_input || 0;
    $("count-draft").textContent = counts.draft_ready || 0;
    $("count-approved").textContent = counts.approved_for_future_submission || 0;
    $("count-submitted").textContent = counts.submitted || 0;
    $("count-closed").textContent = counts.closed || 0;
    $("count-actions").textContent = counts.owner_action_required || 0;
    var summary = data.revenue_summary || {};
    if ($("count-pipeline")) $("count-pipeline").textContent = summary.estimated_pipeline || 0;
    if ($("count-received")) $("count-received").textContent = summary.owner_confirmed_received || 0;
    $("inbox-list").innerHTML = listHtml(data.opportunity_inbox, "No opportunities in inbox.", oppItem);
    $("qualified-list").innerHTML = listHtml(data.qualified_work, "No qualified work.", oppItem);
    $("app-list").innerHTML = listHtml(data.applications, "No applications.", applicationItem);
    $("approval-list").innerHTML = listHtml(data.owner_approvals, "No applications waiting for owner approval.", applicationItem);
    $("follow-list").innerHTML = listHtml(data.follow_ups, "No follow-ups due.", oppItem);
    $("interview-list").innerHTML = listHtml(data.interviews, "No interviews recorded.", oppItem);
    $("won-list").innerHTML = listHtml(data.won_work, "No won work.", oppItem);
    $("action-list").innerHTML = listHtml(data.owner_actions, "No owner actions.", function (row) {
      return "<div class=\"item\"><span class=\"owner-flag\">" + escapeHtml(row.display_label) +
        "</span> · " + escapeHtml(row.action_type) +
        "<div class=\"muted\">" + escapeHtml(row.explanation) + "</div></div>";
    });
    $("revenue-box").textContent = (summary.disclaimer || data.revenue_placeholder || "COMING IN LATER PHASE — owner-entered estimates only. Not earned revenue.") +
      " Pipeline " + (summary.estimated_pipeline || 0) +
      " · contracted " + (summary.contracted_value || 0) +
      " · owner-confirmed received " + (summary.owner_confirmed_received || 0) +
      ". These are not Stripe charges.";
    if ($("engagement-list")) {
      $("engagement-list").innerHTML = listHtml(data.engagements, "No internal engagements.", function (row) {
        return "<div class=\"item\"><strong>" + escapeHtml(row.client_name) + "</strong>" +
          "<div class=\"muted\">" + escapeHtml(row.service) + " · " + escapeHtml(row.frequency) +
          " · " + escapeHtml(row.status) + " · payment " + escapeHtml(row.payment_status) +
          " (tracking only)</div></div>";
      });
    }
    $("audit-list").innerHTML = listHtml(audit, "No activity yet.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.event_type) +
        "<div class=\"muted\">" + escapeHtml(row.summary) + "</div></div>";
    });
    $("filtered-list").innerHTML = listHtml(data.opportunity_list, "No opportunities yet.", oppItem);
    markActiveFilter();
  }
  async function loadDetail(opportunityId) {
    selectedOpportunityId = opportunityId;
    try {
      var detail = await api("/api/nova/work/opportunities/" + opportunityId + "/detail");
      var tracker = detail.tracker || {};
      var opp = tracker.opportunity || {};
      var app = tracker.application;
      var materials = app && app.materials ? app.materials : [];
      var history = tracker.status_history || [];
      var actions = tracker.owner_actions || [];
      var facts = detail.missing_owner_facts || [];
      var checklist = detail.owner_input_checklist || [];
      var split = detail.work_split || {};
      var match = ((opp.qualification || {}).matched_capabilities || []).join(", ") || "none recorded";
      var controls = "<div class=\"action-row\">";
      if (!app) {
        controls += actionButton("prepare", opportunityId, "Prepare application drafts");
      } else {
        controls += applicationActions(app);
      }
      if (!detail.engagement) {
        controls += actionButton("engage", opportunityId, "Create internal engagement (not a contract)");
      }
      controls += actionButton("archive", opportunityId, "Archive");
      controls += "</div>";
      $("detail-box").innerHTML =
        "<div class=\"detail-block\"><strong>" + escapeHtml(opp.opportunity_title) + "</strong>" +
        "<div class=\"muted\">Status " + escapeHtml(opp.status) +
        " · qualification " + escapeHtml(opp.qualification_outcome || "none") +
        (opp.lifecycle_outcome ? " · " + escapeHtml(opp.lifecycle_outcome) : "") +
        (app ? " · " + escapeHtml(approvalLabel(app)) : " · no application yet") +
        "</div></div>" +
        "<div class=\"detail-block\">Capability match: " + escapeHtml(match) + "</div>" +
        "<div class=\"detail-block\">Missing owner facts: " +
        escapeHtml(facts.length ? facts.join(", ") : "none flagged") +
        " — [OWNER INPUT REQUIRED]</div>" +
        "<div class=\"detail-block\">Owner input checklist: " +
        listHtml(checklist, "none", function (row) {
          return "<div class=\"muted\">" + escapeHtml(row.label) + " " + escapeHtml(row.marker) + "</div>";
        }) + "</div>" +
        "<div class=\"detail-block\">Nova can do: " + escapeHtml((split.nova_can_do || []).join("; ") || "none yet") + "</div>" +
        "<div class=\"detail-block\">Owner must do: " + escapeHtml((split.owner_must_do || []).join("; ") || "review and approve") + "</div>" +
        "<div class=\"detail-block\">Unsupported: " + escapeHtml((split.unsupported || []).join("; ") || "none flagged") + "</div>" +
        "<div class=\"detail-block\">Source URL (not fetched): " +
        escapeHtml(detail.source_url_display || "none") + "</div>" +
        "<div class=\"detail-block\">Owner-entered revenue: status " +
        escapeHtml(opp.revenue_status || "NONE") +
        ", estimated " + escapeHtml(opp.estimated_value == null ? "none" : opp.estimated_value) +
        ", quoted " + escapeHtml(opp.quoted_amount == null ? "none" : opp.quoted_amount) +
        ". Not earned revenue.</div>" +
        "<div class=\"detail-block\">Human actions: " +
        listHtml(actions, "none", function (row) {
          return "<div class=\"muted\">" + escapeHtml(row.display_label) + " · " + escapeHtml(row.action_type) + "</div>";
        }) + "</div>" +
        "<div class=\"detail-block\">Materials: " +
        listHtml(materials, "none prepared", function (row) {
          return "<div class=\"muted\">" + escapeHtml(row.kind) + " · " + escapeHtml(row.status) + "</div>";
        }) + "</div>" +
        "<div class=\"detail-block\">History: " +
        listHtml(history, "none", function (row) {
          return "<div class=\"muted\">" + escapeHtml(row.from_status || "start") + " → " + escapeHtml(row.to_status) + "</div>";
        }) + "</div>" +
        "<div class=\"detail-block\"><label>Owner notes<textarea id=\"detail-notes\" rows=\"3\">" +
        escapeHtml(opp.notes || "") + "</textarea></label>" +
        "<div class=\"action-row\">" + actionButton("save-notes", opportunityId, "Save owner notes") + "</div></div>" +
        controls;
    } catch (err) {
      showBanner(err.message);
    }
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
    if (activeFilter) {
      var filtered = await api("/api/nova/work/opportunities?view_filter=" + encodeURIComponent(activeFilter));
      $("filtered-list").innerHTML = listHtml(filtered, "No matching opportunities.", oppItem);
    }
    if (selectedOpportunityId) {
      await loadDetail(selectedOpportunityId);
    }
  }
  async function runWorkAction(action, id) {
    if (action === "prepare") {
      await api("/api/nova/work/applications", {
        method: "POST",
        body: JSON.stringify({ opportunity_id: id })
      });
      showBanner("Drafts prepared. Nothing was submitted externally.", true);
    } else if (action === "ready") {
      await api("/api/nova/work/applications/" + id + "/ready-for-review", { method: "POST" });
      showBanner("Marked ready for owner review.", true);
    } else if (action === "approve") {
      await api("/api/nova/work/applications/" + id + "/decision", {
        method: "POST",
        body: JSON.stringify({ decision: "APPROVED" })
      });
      showBanner("Approved for future submission only. Nova did not send an application.", true);
    } else if (action === "reject") {
      await api("/api/nova/work/applications/" + id + "/decision", {
        method: "POST",
        body: JSON.stringify({ decision: "REJECTED" })
      });
      showBanner("Application rejected. Nothing was sent.", true);
    } else if (action === "needs-changes") {
      await api("/api/nova/work/applications/" + id + "/decision", {
        method: "POST",
        body: JSON.stringify({ decision: "NEEDS_CHANGES" })
      });
      showBanner("Returned for changes. Drafts remain internal.", true);
    } else if (action === "record-manual") {
      await api("/api/nova/work/applications/" + id + "/record-manual-submission", { method: "POST" });
      showBanner("Manual submission recorded. Nova did not contact the source.", true);
    } else if (action === "engage") {
      var detail = await api("/api/nova/work/opportunities/" + id + "/detail");
      var opp = ((detail.tracker || {}).opportunity) || {};
      await api("/api/nova/work/engagements", {
        method: "POST",
        body: JSON.stringify({
          opportunity_id: id,
          client_name: opp.company_name || "Unknown client",
          service: opp.opportunity_title || "Internal work tracking",
          frequency: "one_time"
        })
      });
      showBanner("Internal engagement created. Not a signed contract. Nova did not contact the client.", true);
    } else if (action === "archive") {
      await api("/api/nova/work/opportunities/" + id, {
        method: "PATCH",
        body: JSON.stringify({ archived: true })
      });
      showBanner("Opportunity archived.", true);
    } else if (action === "save-notes") {
      var notesEl = $("detail-notes");
      await api("/api/nova/work/opportunities/" + id, {
        method: "PATCH",
        body: JSON.stringify({ notes: notesEl ? notesEl.value : "" })
      });
      showBanner("Owner notes saved.", true);
    } else {
      return;
    }
    await refresh();
  }
  document.querySelector(".work-main").addEventListener("click", async function (event) {
    var button = event.target && event.target.closest ? event.target.closest("[data-work-action]") : null;
    if (button) {
      event.preventDefault();
      event.stopPropagation();
      try {
        await runWorkAction(button.getAttribute("data-work-action"), button.getAttribute("data-id"));
      } catch (err) {
        showBanner(err.message);
      }
      return;
    }
    var item = event.target && event.target.closest ? event.target.closest("[data-opportunity-id]") : null;
    if (item) {
      loadDetail(item.getAttribute("data-opportunity-id"));
    }
  });
  $("filter-row").addEventListener("click", async function (event) {
    var target = event.target;
    if (!target || !target.getAttribute) return;
    if (!target.hasAttribute("data-filter")) return;
    activeFilter = target.getAttribute("data-filter") || "";
    try { await refresh(); } catch (err) { showBanner(err.message); }
  });
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
          estimated_value: amount === "" ? null : Number(amount),
          skills_required: $("opp-skills").value.split(",").map(function (item) { return item.trim(); }).filter(Boolean),
          source_url: $("opp-source-url").value || null,
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
