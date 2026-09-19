"use strict";

(function () {
  var activeFilter = "";
  var selectedOpportunityId = "";
  var activeTab = "overview";
  var factFilter = "all";
  var factCatalog = null;
  var queueOffset = 0;
  var queueLimit = 25;
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
  function liveJobItem(row) {
    var opp = row.opportunity || row;
    var title = opp.title || opp.opportunity_title || "Opportunity";
    var company = opp.company_name || "Unknown company";
    var url = opp.source_url || "";
    var score = opp.relevance_score;
    var meta = [];
    if (opp.geography) meta.push(opp.geography);
    if (opp.compensation_text) meta.push(opp.compensation_text);
    if (score != null) meta.push("match score " + score);
    return "<div class=\"item\"><strong>" + escapeHtml(title) + "</strong>" +
      "<div class=\"muted\">" + escapeHtml(company) + (meta.length ? " · " + escapeHtml(meta.join(" · ")) : "") + "</div>" +
      (url ? "<div><a href=\"" + escapeHtml(url) + "\" target=\"_blank\" rel=\"noopener noreferrer\">Open job source</a></div>" : "") +
      "</div>";
  }
  async function refreshLiveDiscoveryStatus() {
    if (!$("live-job-status") || !token()) return;
    try {
      var guards = await api("/api/nova/v3/guardrails");
      var enabled = guards.LIVE_DISCOVERY_ENABLED === true;
      $("live-job-status").textContent = enabled
        ? "LIVE DISCOVERY READY · External submission remains approval-controlled/off until the submission adapter is verified."
        : "LIVE DISCOVERY OFF · Set NOVA_V3_LIVE_DISCOVERY_ENABLED=true in the production environment, then redeploy. External submission remains off.";
    } catch (err) {
      $("live-job-status").textContent = "Live-discovery status unavailable: " + err.message;
    }
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
  function factMatchesFilter(row) {
    var status = String(row.value_status || "MISSING").toUpperCase();
    if (factFilter === "missing") return status === "MISSING";
    if (factFilter === "provided") return status === "PROVIDED" || status === "OWNER_PROVIDED";
    if (factFilter === "verified") return status === "VERIFIED";
    if (factFilter === "expired") return status === "EXPIRED" || Boolean(row.expires_at);
    if (factFilter === "required") return Boolean(row.required_before_live) && (status === "MISSING" || status === "EXPIRED");
    return true;
  }
  function factHint(row) {
    if (row.value_kind === "flag") return "Readiness flag only: OWNER_SAYS_READY, OWNER_SAYS_NOT_READY, w9_ready, tax_information_ready, banking_ready, or NOT_APPLICABLE.";
    if (row.value_kind === "decision" && row.fact_id === "ai_use_disclosure_decision") return "Use AI_ASSISTANCE_USED_DISCLOSE, AI_ASSISTANCE_USED_OWNER_WILL_DECIDE_PER_PLATFORM, NO_AI_ASSISTANCE_CLAIMED, or NOT_APPLICABLE.";
    if (row.value_kind === "decision") return "Use SUBCONTRACTOR_ASSISTANCE_ALLOWED, SUBCONTRACTOR_ASSISTANCE_NOT_ALLOWED, OWNER_WILL_DECIDE_PER_ENGAGEMENT, or NOT_APPLICABLE.";
    if (row.value_kind === "status") return "Use OWNER_SAYS_READY, insurance_verified / license_verified, or a short status. No policy or license numbers.";
    if (row.value_kind === "email") return "Business email only. No secrets.";
    if (row.value_kind === "phone") return "Business phone only. No secrets.";
    return "Non-sensitive owner text only. No EIN, SSN, bank numbers, or keys.";
  }
  function renderFacts(catalog) {
    factCatalog = catalog || factCatalog;
    if (!factCatalog || !$("fact-list")) return;
    var ready = factCatalog.readiness || {};
    if ($("fact-readiness")) {
      $("fact-readiness").textContent =
        "Required " + (ready.total_required_facts || 0) +
        " · provided " + (ready.provided_facts || 0) +
        " · verified " + (ready.verified_facts || 0) +
        " · missing " + (ready.missing_facts || 0) +
        " · expired " + (ready.expired_facts || 0) +
        " · " + (ready.percentage_complete || 0) + "% complete. Nova reuses PROVIDED/VERIFIED profile facts to tailor each application package. Nothing was submitted or charged.";
    }
    renderFactStatus(ready);
    var rows = (factCatalog.facts || []).filter(factMatchesFilter);
    $("fact-list").innerHTML = listHtml(rows, "No facts match this filter.", function (row) {
      var current = row.value_status === "MISSING" ? "" : (row.value_display || "");
      return "<div class=\"item\" data-fact-id=\"" + escapeHtml(row.fact_id) + "\">" +
        "<strong>" + escapeHtml(row.label) + "</strong>" +
        "<div class=\"muted\">" + escapeHtml(row.category) +
        " · <span class=\"fact-status " + escapeHtml(String(row.value_status || "").toLowerCase()) + "\">" +
        escapeHtml(row.value_status) + "</span>" +
        (row.required_before_live ? " · required before live V1" : " · optional") +
        " · source " + escapeHtml(row.source || "OWNER") + "</div>" +
        "<div class=\"muted\">" + escapeHtml(factHint(row)) + "</div>" +
        "<form class=\"fact-form\" data-fact-form=\"" + escapeHtml(row.fact_id) + "\">" +
        "<label>Status" +
        "<select name=\"value_status\">" +
        ["MISSING", "PROVIDED", "VERIFIED", "EXPIRED", "NOT_APPLICABLE"].map(function (status) {
          return "<option value=\"" + status + "\"" + (row.value_status === status ? " selected" : "") + ">" + status + "</option>";
        }).join("") +
        "</select></label>" +
        "<label>Value<input name=\"value_display\" maxlength=\"400\" value=\"" + escapeHtml(current) + "\" /></label>" +
        "<label>Notes<textarea name=\"notes\" rows=\"2\" maxlength=\"2000\">" + escapeHtml(row.notes || "") + "</textarea></label>" +
        (row.value_status === "VERIFIED" ? "<label><input type=\"checkbox\" name=\"confirm_overwrite\" /> Confirm overwrite of verified fact</label>" : "") +
        "<div class=\"action-row\"><button type=\"submit\">Save fact</button></div>" +
        "<div class=\"fact-error\" data-fact-error=\"" + escapeHtml(row.fact_id) + "\"></div>" +
        "</form></div>";
    });
  }
  function renderFactStatus(ready) {
    var text = "Master work profile: verified " + (ready.verified || ready.verified_facts || 0) +
      " · missing " + (ready.missing || ready.missing_facts || 0) +
      " · expired " + (ready.expired || ready.expired_facts || 0) +
      " · " + (ready.percentage_complete || 0) + "% ready. Sensitive values are not shown.";
    ["queue-fact-status", "recon-fact-status"].forEach(function (id) {
      if ($(id)) $(id).textContent = text;
    });
  }
  function queueParams() {
    var params = new URLSearchParams();
    var status = $("queue-status") ? $("queue-status").value : "";
    var attention = $("queue-attention") ? $("queue-attention").value : "";
    var sort = $("queue-sort") ? $("queue-sort").value : "updated_at";
    var order = $("queue-order") ? $("queue-order").value : "desc";
    if (status) params.set("status", status);
    if (attention) params.set("attention", attention);
    params.set("sort", sort || "updated_at");
    params.set("order", order || "desc");
    params.set("limit", String(queueLimit));
    params.set("offset", String(queueOffset));
    return params.toString();
  }
  function renderQueue(page) {
    if (!$("queue-list")) return;
    var items = (page && page.items) || [];
    var facts = (page && page.owner_fact_status) || {};
    renderFactStatus(facts);
    if ($("count-queue")) $("count-queue").textContent = (page.active_count != null ? page.active_count : page.total_matched) || 0;
    if ($("count-overdue")) $("count-overdue").textContent = page.overdue_count || 0;
    if ($("queue-meta")) {
      $("queue-meta").textContent =
        (page.empty ? "Queue is empty. " : (items.length + " shown of " + (page.total_matched || 0) + ". ")) +
        (page.historical_excluded ? "Archived and complete work are excluded from default active counts. " : "") +
        "Overdue " + (page.overdue_count || 0) +
        " · blocked " + (page.blocked_count || 0) +
        " · owner action " + (page.owner_action_count || 0) +
        ". Internal tracking only. Offset " + (page.offset || 0) + ".";
    }
    $("queue-list").innerHTML = listHtml(items, "No internal work items match these filters.", function (row) {
      return "<div class=\"item\">" +
        "<strong>" + escapeHtml(row.client_name || row.engagement_id) + "</strong>" +
        "<div class=\"muted\">" + escapeHtml(row.queue_status || row.status) +
        (row.overdue ? " · OVERDUE" : "") +
        (row.owner_action_required ? " · OWNER ACTION REQUIRED" : "") +
        (row.attention_state && row.attention_state !== row.queue_status ? " · " + escapeHtml(row.attention_state) : "") +
        " · priority " + escapeHtml(row.priority || "normal") +
        (row.due_date ? " · due " + escapeHtml(row.due_date) : "") +
        (row.opportunity_id ? " · opportunity " + escapeHtml(row.opportunity_id) : "") +
        " · engagement " + escapeHtml(row.engagement_id) +
        (row.organization_id ? " · org " + escapeHtml(row.organization_id) : "") +
        "</div>" +
        (row.blockers ? "<div class=\"muted\">Blocked: " + escapeHtml(row.blockers) + "</div>" : "") +
        "<div class=\"muted\">External submit disabled. Client contact disabled. Financial execution disabled.</div></div>";
    });
  }
  function renderReconciliation(body) {
    if (!$("recon-summary")) return;
    var facts = (body && body.owner_fact_status) || {};
    renderFactStatus(facts);
    var mismatch = (body && body.mismatch) || {};
    var amicor = (body && body.amicor) || {};
    var client = (body && body.client_context) || {};
    $("recon-summary").innerHTML =
      "<div class=\"recon-grid\">" +
      "<div class=\"item\"><strong>AMICOR expected</strong><div class=\"muted\">" + escapeHtml((amicor.expected_revenue || {}).amount || body.contracted_amount) + " · AMICOR ledger</div></div>" +
      "<div class=\"item\"><strong>AMICOR estimated</strong><div class=\"muted\">" + escapeHtml(body.estimated_amount) + " · AMICOR ledger, not received</div></div>" +
      "<div class=\"item\"><strong>AMICOR contracted</strong><div class=\"muted\">" + escapeHtml(body.contracted_amount) + " · AMICOR ledger, not received</div></div>" +
      "<div class=\"item\"><strong>Client billed draft</strong><div class=\"muted\">" + escapeHtml((client.billed_amount || {}).amount || body.invoice_support_amount) + " · not a real invoice sent</div></div>" +
      "<div class=\"item\"><strong>Client/opportunity contract</strong><div class=\"muted\">" + escapeHtml((client.contract_opportunity_amount || {}).amount) + " · context only</div></div>" +
      "<div class=\"item\"><strong>AMICOR owner-confirmed received</strong><div class=\"muted\">" + escapeHtml(body.owner_confirmed_received_amount) + " · current/active AMICOR ledger</div></div>" +
      "<div class=\"item\"><strong>Historical archived AMICOR received</strong><div class=\"muted\">" + escapeHtml(((body.historical_archived || {}).owner_confirmed_received) || 0) + " · historical only, not in current totals, not deleted</div></div>" +
      "<div class=\"item\"><strong>Reconciliation state</strong><div class=\"muted\">" + escapeHtml(body.reconciliation_state) +
      (mismatch.has_mismatch ? " · mismatch flagged between AMICOR ledger and client/opportunity context" : " · no AMICOR vs client amount mismatch") + "</div></div>" +
      "</div>" +
      (mismatch.has_mismatch ? "<p class=\"hint\">Mismatch: " + escapeHtml(Object.keys(mismatch).filter(function (key) { return mismatch[key] === true && key !== "invoice_support_is_not_received" && key !== "invoice_support_is_not_a_sent_invoice" && key !== "has_mismatch"; }).join(", ") || "sources disagree") + ". Context amounts are not added into AMICOR totals.</p>" : "") +
      "<p class=\"hint\">" + escapeHtml(body.disclaimer) + " Processor confirmed payment: no. Stripe confirmed payment: no. Double counted: no.</p>";
    $("recon-entries").innerHTML = listHtml(body.entries, "No internal revenue entries.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.stage) + " · " + escapeHtml(row.amount) + "</strong>" +
        "<div class=\"muted\">" +
        (row.engagement_id ? "engagement " + escapeHtml(row.engagement_id) + " · " : "") +
        (row.opportunity_id ? "opportunity " + escapeHtml(row.opportunity_id) + " · " : "") +
        (row.owner_confirmed ? "owner confirmed" : "not owner-confirmed") +
        (row.remaining_amount ? " · remaining expected " + escapeHtml(row.remaining_amount) : "") +
        (row.historical ? " · historical/archived, not in current totals" : " · current AMICOR ledger") +
        " · processor confirmed: no</div></div>";
    });
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
    if ($("count-quoted")) $("count-quoted").textContent = summary.quoted_pipeline || 0;
    if ($("count-contracted")) $("count-contracted").textContent = summary.contracted_value || 0;
    if ($("count-received")) $("count-received").textContent = summary.owner_confirmed_received || 0;
    if ($("count-remaining")) $("count-remaining").textContent = summary.remaining_balance || 0;
    if ($("count-historical")) $("count-historical").textContent = summary.historical_archived_received || 0;
    if ($("count-client-billed")) $("count-client-billed").textContent = summary.client_billed_amount || 0;
    if ($("count-opp-contract")) $("count-opp-contract").textContent = summary.contract_opportunity_amount || 0;
    if ($("count-tasks")) $("count-tasks").textContent = counts.tasks_due || 0;
    if ($("count-deliverables")) $("count-deliverables").textContent = counts.deliverables_pending || 0;
    if ($("count-recurring")) $("count-recurring").textContent = counts.recurring_overdue || 0;
    if ($("count-reports")) $("count-reports").textContent = counts.reports_awaiting_review || 0;
    if ($("count-invoices")) $("count-invoices").textContent = counts.invoice_support_drafts || 0;
    if ($("count-blocked")) $("count-blocked").textContent = counts.blocked_work || 0;
    if ($("count-facts-missing")) $("count-facts-missing").textContent = counts.facts_missing || 0;
    if ($("count-facts-ready")) $("count-facts-ready").textContent = (counts.facts_readiness_percent || 0) + "%";
    $("inbox-list").innerHTML = listHtml(data.opportunity_inbox, "No opportunities in inbox.", oppItem);
    $("qualified-list").innerHTML = listHtml(data.qualified_work, "No qualified work.", oppItem);
    $("app-list").innerHTML = listHtml(data.applications, "No applications.", applicationItem);
    $("approval-list").innerHTML = listHtml(data.owner_approvals, "No applications waiting for owner approval.", applicationItem);
    if ($("needs-review-list")) $("needs-review-list").innerHTML = listHtml(data.owner_approvals, "Nothing needs owner review.", applicationItem);
    if ($("approved-list")) $("approved-list").innerHTML = listHtml(
      (data.applications || []).filter(function (row) { return row.approved_for_future_submission && !row.manual_submission_recorded; }),
      "No approved-for-future-submission items.",
      applicationItem
    );
    if ($("submitted-list")) $("submitted-list").innerHTML = listHtml(
      (data.applications || []).filter(function (row) { return row.manual_submission_recorded; }),
      "No manually submitted records. NOT SENT BY NOVA.",
      applicationItem
    );
    if ($("active-work-list")) $("active-work-list").innerHTML = listHtml(data.engagements, "No active internal work.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.client_name) + "</strong>" +
        "<div class=\"muted\">" + escapeHtml(row.status) + " · PAYMENT NOT CONFIRMED unless owner-confirmed received</div></div>";
    });
    if ($("completed-list")) $("completed-list").innerHTML = listHtml(
      (data.engagements || []).filter(function (row) { return row.status === "COMPLETE" || row.queue_status === "COMPLETE"; }),
      "No completed internal work.",
      function (row) {
        return "<div class=\"item\"><strong>" + escapeHtml(row.client_name) + "</strong><div class=\"muted\">Complete is not paid. RECEIVED CONFIRMED BY OWNER is separate.</div></div>";
      }
    );
    $("follow-list").innerHTML = listHtml(data.follow_ups, "No follow-ups due.", oppItem);
    $("interview-list").innerHTML = listHtml(data.interviews, "No interviews recorded.", oppItem);
    $("won-list").innerHTML = listHtml(data.won_work, "No won work.", oppItem);
    $("action-list").innerHTML = listHtml(data.owner_actions, "No owner actions.", function (row) {
      return "<div class=\"item\"><span class=\"owner-flag\">" + escapeHtml(row.display_label) +
        "</span> · " + escapeHtml(row.action_type) +
        "<div class=\"muted\">" + escapeHtml(row.explanation) + "</div></div>";
    });
    $("revenue-box").textContent = (summary.disclaimer || data.revenue_placeholder || "COMING IN LATER PHASE — owner-entered estimates only. Not earned revenue.") +
      " AMICOR expected " + (summary.amicor_expected_revenue || 0) +
      " · AMICOR estimated " + (summary.estimated_pipeline || 0) +
      " · AMICOR contracted " + (summary.contracted_value || 0) +
      " · AMICOR owner-confirmed received " + (summary.owner_confirmed_received || 0) +
      " · client billed draft " + (summary.client_billed_amount || 0) +
      " · client/opportunity contract context " + (summary.contract_opportunity_amount || 0) +
      ". These are not Stripe charges. Sources are not added together.";
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
    if ($("pilot-audit-list")) {
      $("pilot-audit-list").innerHTML = listHtml(audit, "No audit events.", function (row) {
        return "<div class=\"item\">" + escapeHtml(row.event_type) +
          "<div class=\"muted\">" + escapeHtml(row.summary) + " · " + escapeHtml(row.entity_type || "") +
          " · " + escapeHtml(row.previous_state || "") + " → " + escapeHtml(row.new_state || "") + "</div></div>";
      });
    }
    if ($("archive-list")) {
      $("archive-list").innerHTML = listHtml(data.rejected_or_archived, "No archived opportunities.", oppItem);
    }
    if ($("task-list")) {
      var tasks = [];
      (data.engagements || []).forEach(function (eng) {
        (eng.tasks || []).forEach(function (task) {
          tasks.push({
            title: task.title,
            status: task.status,
            party: task.responsible_party,
            client: eng.client_name
          });
        });
      });
      $("task-list").innerHTML = listHtml(tasks, "No internal tasks.", function (row) {
        return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong>" +
          "<div class=\"muted\">" + escapeHtml(row.client) + " · " + escapeHtml(row.party) +
          " · " + escapeHtml(row.status) + "</div></div>";
      });
    }
    if ($("engagement-list")) {
      $("engagement-list").innerHTML = listHtml(data.engagements, "No internal engagements.", function (row) {
        return "<div class=\"item\"><strong>" + escapeHtml(row.client_name) + "</strong>" +
          "<div class=\"muted\">" + escapeHtml(row.service) + " · queue " + escapeHtml(row.queue_status || row.status) +
          " · " + escapeHtml(row.priority || "normal") +
          (row.due_date ? " · due " + escapeHtml(row.due_date) : "") +
          " · payment " + escapeHtml(row.payment_status) +
          " (tracking only)</div></div>";
      });
    }
    if ($("deliverable-list")) {
      $("deliverable-list").innerHTML = "Sign in to load deliverables, or open an engagement. Delivered requires owner confirmation.";
    }
    $("filtered-list").innerHTML = listHtml(data.opportunity_list, "No opportunities yet.", oppItem);
    markActiveFilter();
    applyTab();
  }
  function applyTab() {
    var panels = document.querySelectorAll("[data-panel]");
    panels.forEach(function (panel) {
      var names = (panel.getAttribute("data-panel") || "").split(/\s+/);
      var show = activeTab === "overview" || names.indexOf(activeTab) !== -1;
      panel.classList.toggle("hidden-panel", !show);
    });
    var buttons = document.querySelectorAll("#tab-row [data-tab]");
    buttons.forEach(function (button) {
      var on = (button.getAttribute("data-tab") || "") === activeTab;
      button.classList.toggle("filter-on", on);
      button.setAttribute("aria-selected", on ? "true" : "false");
    });
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
    if ($("filtered-list")) $("filtered-list").setAttribute("aria-busy", "true");
    var data = await api("/api/nova/work/dashboard");
    var audit = [];
    try { audit = await api("/api/nova/work/audit"); } catch (_) { audit = []; }
    renderDashboard(data, audit);
    await refreshLiveDiscoveryStatus();
    if (activeFilter) {
      var filtered = await api("/api/nova/work/opportunities?view_filter=" + encodeURIComponent(activeFilter) + "&limit=100");
      $("filtered-list").innerHTML = listHtml(filtered, "No matching opportunities.", oppItem);
    }
    if ($("filtered-list")) $("filtered-list").removeAttribute("aria-busy");
    if (activeTab === "deliverables") {
      try {
        var dels = await api("/api/nova/work/deliverables?limit=100");
        if ($("deliverable-list")) {
          $("deliverable-list").innerHTML = listHtml(dels, "No internal deliverables.", function (row) {
            return "<div class=\"item\"><strong>" + escapeHtml(row.deliverable_type) + "</strong>" +
              "<div class=\"muted\">" + escapeHtml(row.delivery_status) +
              (row.owner_confirmed_delivered ? " · owner confirmed" : " · not transmitted") +
              "</div></div>";
          });
        }
      } catch (_) {}
    }
    if (activeTab === "recurring") {
      try {
        var series = await api("/api/nova/work/recurring");
        if ($("recurring-list")) {
          $("recurring-list").innerHTML = listHtml(series, "No recurring series.", function (row) {
            return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong>" +
              "<div class=\"muted\">" + escapeHtml(row.frequency) + " · " + escapeHtml(row.status) +
              " · " + escapeHtml(row.attention_state) +
              " · next " + escapeHtml(row.next_work_date || "none") +
              " · notifications off</div></div>";
          });
        }
      } catch (_) {}
    }
    if (activeTab === "reports") {
      try {
        var reports = await api("/api/nova/work/reports");
        if ($("report-list")) {
          $("report-list").innerHTML = listHtml(reports, "No weekly report drafts.", function (row) {
            return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong>" +
              "<div class=\"muted\">" + escapeHtml(row.status) +
              " · send disabled · generating a report is not sending it</div></div>";
          });
        }
      } catch (_) {}
    }
    if (activeTab === "owner-facts" || $("fact-list")) {
      try {
        renderFacts(await api("/api/nova/work/owner-facts"));
      } catch (_) {}
    }
    if (activeTab === "queue" || $("queue-list")) {
      try {
        renderQueue(await api("/api/nova/work/queue?" + queueParams()));
      } catch (_) {}
    }
    if (activeTab === "reconciliation" || $("recon-summary")) {
      try {
        renderReconciliation(await api("/api/nova/work/reconciliation"));
      } catch (_) {}
    }
    if (activeTab === "invoice-support") {
      try {
        var invoices = await api("/api/nova/work/invoice-support");
        if ($("invoice-list")) {
          $("invoice-list").innerHTML = listHtml(invoices, "No invoice-support drafts.", function (row) {
            return "<div class=\"item\"><strong>" + escapeHtml(row.client_name) + "</strong>" +
              "<div class=\"muted\">" + escapeHtml(row.status) +
              " · subtotal " + escapeHtml(row.draft_subtotal) +
              " · client billed draft · not AMICOR received · not a Stripe invoice</div></div>";
          });
        }
      } catch (_) {}
    }
    if (activeTab === "v2-actions" || activeTab === "overview") {
      try {
        var board = await api("/api/nova/work/v2/actions/board");
        function v2Item(row) {
          return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong>" +
            "<div class=\"muted\">" + escapeHtml(row.action_type) + " · " + escapeHtml(row.status) +
            " · approval is not execution · live execution off</div></div>";
        }
        if ($("v2-pending-list")) $("v2-pending-list").innerHTML = listHtml(board.pending_owner_approval, "No pending owner approvals.", v2Item);
        if ($("v2-waiting-list")) $("v2-waiting-list").innerHTML = listHtml(board.approved_waiting, "Nothing approved and waiting.", v2Item);
        if ($("waiting-list")) $("waiting-list").innerHTML = listHtml(board.approved_waiting, "Nothing waiting on owner-controlled execution. Live execution remains off.", v2Item);
        if ($("v2-blocked-list")) $("v2-blocked-list").innerHTML = listHtml(board.blocked, "No blocked live actions.", v2Item);
        if ($("v2-completed-list")) $("v2-completed-list").innerHTML = listHtml(board.completed, "No completed live actions. Live execution remains off.", v2Item);
        if ($("v2-failed-list")) $("v2-failed-list").innerHTML = listHtml(board.failed, "No failed live-action attempts.", v2Item);
        var trail = await api("/api/nova/work/v2/audit?limit=50");
        if ($("v2-audit-list")) {
          $("v2-audit-list").innerHTML = listHtml(trail, "No live-action audit records.", function (row) {
            return "<div class=\"item\"><strong>" + escapeHtml(row.action_type) + "</strong>" +
              "<div class=\"muted\">" + escapeHtml(row.outcome) + " · " + escapeHtml(row.reason) +
              " · " + escapeHtml(row.timestamp || "") + "</div></div>";
          });
        }
      } catch (_) {}
    }
    if (activeTab === "v2-capabilities" || activeTab === "partial-payments" || activeTab === "historical") {
      try {
        var caps = await api("/api/nova/work/v2/capabilities");
        var items = Object.keys(caps.capabilities || {}).map(function (key) { return caps.capabilities[key]; });
        if ($("v2-capability-list")) {
          $("v2-capability-list").innerHTML = listHtml(items, "No capabilities.", function (row) {
            return "<div class=\"item\"><strong>" + escapeHtml(row.capability) + "</strong>" +
              "<div class=\"muted\">" + (row.enabled ? "enabled" : "DISABLED") +
              " · default off · live adapter not implemented · secrets not exposed</div></div>";
          });
        }
        var status = await api("/api/nova/work/v2/status");
        if ($("v2-status-box")) {
          $("v2-status-box").innerHTML =
            "<div class=\"item\"><strong>Live execution</strong><div class=\"muted\">" + escapeHtml(status.live_execution_state) +
            " · worker " + escapeHtml(String(status.continuous_worker)) +
            " · scheduler " + escapeHtml(status.scheduler_state) + "</div></div>" +
            "<div class=\"item\"><strong>Pending / expired / failed</strong><div class=\"muted\">pending " +
            escapeHtml(status.pending_actions) + " · expired " + escapeHtml(status.approval_expirations) +
            " · final failures " + escapeHtml(status.final_failures) + "</div></div>";
        }
        var prep = await api("/api/nova/work/v2/revenue/preparation");
        if ($("partial-list")) {
          $("partial-list").innerHTML = prep.partially_paid
            ? "<div class=\"item\"><strong>PARTIALLY_PAID remaining " + escapeHtml(prep.remaining_balance) +
              "</strong><div class=\"muted\">RECEIVED CONFIRMED BY OWNER. Processor events are not cash.</div></div>"
            : "No partial payments.";
        }
        if ($("historical-list")) {
          $("historical-list").innerHTML = listHtml(prep.historical_corrections, "No historical corrections. Archived received stays queryable in reconciliation.", function (row) {
            return "<div class=\"item\"><strong>HISTORICAL " + escapeHtml(row.amount) + "</strong>" +
              "<div class=\"muted\">" + escapeHtml(row.reason) + " · not applied to current totals</div></div>";
          });
        }
      } catch (_) {}
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
  if ($("tab-row")) {
    $("tab-row").addEventListener("click", function (event) {
      var target = event.target;
      if (!target || !target.getAttribute || !target.hasAttribute("data-tab")) return;
      activeTab = target.getAttribute("data-tab") || "overview";
      applyTab();
      if (activeTab === "owner-facts" || activeTab === "queue" || activeTab === "reconciliation" || activeTab === "v2-actions" || activeTab === "v2-capabilities") {
        refresh().catch(function (err) { showBanner(err.message); });
      }
    });
  }
  if ($("fact-filter-row")) {
    $("fact-filter-row").addEventListener("click", function (event) {
      var target = event.target;
      if (!target || !target.getAttribute || !target.hasAttribute("data-fact-filter")) return;
      factFilter = target.getAttribute("data-fact-filter") || "all";
      var buttons = document.querySelectorAll("#fact-filter-row [data-fact-filter]");
      buttons.forEach(function (button) {
        button.classList.toggle("filter-on", (button.getAttribute("data-fact-filter") || "") === factFilter);
      });
      renderFacts(factCatalog);
    });
  }
  function applyQueueFilters() {
    queueOffset = 0;
    refresh().catch(function (err) { showBanner(err.message); });
  }
  if ($("queue-apply")) {
    $("queue-apply").addEventListener("click", function () { applyQueueFilters(); });
  }
  ["queue-status", "queue-attention", "queue-sort", "queue-order"].forEach(function (id) {
    if ($(id)) $(id).addEventListener("change", applyQueueFilters);
  });
  if ($("queue-prev")) {
    $("queue-prev").addEventListener("click", function () {
      queueOffset = Math.max(0, queueOffset - queueLimit);
      refresh().catch(function (err) { showBanner(err.message); });
    });
  }
  if ($("queue-next")) {
    $("queue-next").addEventListener("click", function () {
      queueOffset = queueOffset + queueLimit;
      refresh().catch(function (err) { showBanner(err.message); });
    });
  }
  document.querySelector(".work-main").addEventListener("submit", async function (event) {
    var form = event.target && event.target.closest ? event.target.closest("[data-fact-form]") : null;
    if (!form) return;
    event.preventDefault();
    var factId = form.getAttribute("data-fact-form");
    var errorEl = document.querySelector("[data-fact-error=\"" + factId + "\"]");
    if (errorEl) errorEl.textContent = "";
    var confirmBox = form.querySelector("[name=\"confirm_overwrite\"]");
    try {
      var catalog = await api("/api/nova/work/owner-facts/" + encodeURIComponent(factId), {
        method: "PUT",
        body: JSON.stringify({
          value_status: form.querySelector("[name=\"value_status\"]").value,
          value_display: form.querySelector("[name=\"value_display\"]").value,
          notes: form.querySelector("[name=\"notes\"]").value,
          confirm_overwrite: !!(confirmBox && confirmBox.checked)
        })
      });
      renderFacts(catalog);
      showBanner("Owner fact saved. Nothing was submitted, sent, or charged.", true);
      await refresh();
    } catch (err) {
      if (errorEl) errorEl.textContent = err.message;
      showBanner(err.message);
    }
  });
  if ($("live-job-form")) {
    $("live-job-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      var query = $("live-job-query").value.trim();
      if (!query) return;
      $("live-job-status").textContent = "Nova is searching live jobs, ranking matches, and preparing the strongest candidates for owner approval...";
      $("live-job-results").innerHTML = "";
      try {
        var body = await api("/api/nova/v3/live/jobs/prepare", {
          method: "POST",
          body: JSON.stringify({
            query: query,
            limit: Number($("live-job-limit").value || 10),
            save_limit: 5,
            prepare_limit: Number($("live-job-prepare-limit").value || 3),
            min_relevance_score: 1
          })
        });
        var prepared = body.prepared || [];
        $("live-job-status").textContent =
          "Found/ranked " + (body.ranked_count || 0) + " · selected " + (body.selected_count || 0) +
          " · prepared " + (body.prepared_count || 0) +
          " for your approval. External action taken: " + String(body.external_action_taken === true) + ".";
        $("live-job-results").innerHTML = listHtml(prepared, "No sufficiently relevant jobs were prepared. Try a broader search.", liveJobItem);
        showBanner("Live job discovery finished. Review prepared opportunities before any external submission.", true);
        await refresh();
      } catch (err) {
        $("live-job-status").textContent = err.message;
        showBanner(err.message);
      }
    });
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
