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
  function hideBanner() {
    var el = $("banner");
    if (!el) return;
    el.textContent = "";
    el.classList.add("hidden");
    el.classList.remove("ok");
  }
  function setVoiceStatus(message) {
    if ($("voice-status")) $("voice-status").textContent = message;
  }
  var novaHumanVoice = null;
  function getNovaHumanVoice() {
    if (!novaHumanVoice && window.AmiCorHumanVoice && window.AmiCorHumanVoice.createEngine) {
      novaHumanVoice = window.AmiCorHumanVoice.createEngine({
        browserFallbackEnabled: true,
        onState: function (state) {
          if (state && state.speaking) setVoiceStatus("Nova is speaking naturally…");
          else if (state && state.reason) setVoiceStatus("Ready.");
        }
      });
    }
    return novaHumanVoice;
  }
  function stopNovaSpeaking() {
    var engine = getNovaHumanVoice();
    if (engine) {
      engine.stop("owner-stop");
      setVoiceStatus("Nova stopped speaking.");
      return;
    }
    if (!window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
      setVoiceStatus("Nova stopped speaking.");
    } catch (_) {}
  }
  function speakNova(text) {
    if (!text) return;
    var engine = getNovaHumanVoice();
    if (engine) {
      engine.speak(String(text), { persona: "Warm Conversational" }).catch(function () {
        setVoiceStatus("Natural voice is temporarily unavailable.");
      });
      return;
    }
    if (!window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
      var utterance = new SpeechSynthesisUtterance(String(text));
      utterance.lang = "en-US";
      utterance.rate = 0.98;
      utterance.pitch = 1.01;
      utterance.onstart = function () { setVoiceStatus("Nova is speaking…"); };
      utterance.onend = function () { setVoiceStatus("Ready."); };
      window.speechSynthesis.speak(utterance);
    } catch (_) {}
  }
  function startVoiceInput() {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setVoiceStatus("Voice input is not supported in this browser. You can still type to Nova.");
      return;
    }
    if (!token()) {
      showBanner("Sign in before using voice input.");
      $("login-form").classList.remove("hidden");
      return;
    }
    var recognition = new SR();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    setVoiceStatus("Listening… speak now.");
    if ($("ask-mic")) $("ask-mic").textContent = "Listening…";
    recognition.onresult = function (event) {
      var transcript = event.results && event.results[0] && event.results[0][0]
        ? event.results[0][0].transcript
        : "";
      $("ask-input").value = transcript || "";
      setVoiceStatus(transcript ? "Heard: " + transcript : "I did not catch that. Try again.");
      if (transcript) {
        $("ask-form").requestSubmit();
      }
    };
    recognition.onerror = function (event) {
      var code = (event && event.error) || "unavailable";
      if (code === "aborted") {
        setVoiceStatus("Listening stopped.");
        return;
      }
      setVoiceStatus("Microphone error: " + code + ".");
    };
    recognition.onend = function () {
      if ($("ask-mic")) $("ask-mic").textContent = "🎤 Talk";
    };
    try {
      recognition.start();
    } catch (_) {
      setVoiceStatus("Microphone could not start. Check browser microphone permission.");
      if ($("ask-mic")) $("ask-mic").textContent = "🎤 Talk";
    }
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
  var selectedActionId = "";
  var selectedSourceRefId = "";
  function cardMeta(card) {
    return "<div class=\"meta\">" +
      "<span>Source: " + escapeHtml(card.source_label || card.source_module || "") + "</span>" +
      "<span>Priority: " + escapeHtml(card.priority_band || String(card.priority || "")) + "</span>" +
      "<span>Next: " + escapeHtml(card.recommended_action || "") + "</span>" +
      (card.risk_class ? "<span>Risk: " + escapeHtml(card.risk_class) + "</span>" : "") +
      (card.approval_state ? "<span>Approval: " + escapeHtml(card.approval_state) + "</span>" : "") +
      (card.execution_state ? "<span>Execution: " + escapeHtml(card.execution_state) + "</span>" : "") +
      (card.sender ? "<span>From: " + escapeHtml(card.sender) + "</span>" : "") +
      (card.received_at ? "<span>Received: " + escapeHtml(card.received_at) + "</span>" : "") +
      (card.unread != null ? "<span>" + (card.unread ? "Unread" : "Read") + "</span>" : "") +
      (card.important ? "<span>Important</span>" : "") +
      (card.provider ? "<span>Provider: " + escapeHtml(card.provider) + "</span>" : "") +
      "</div>" +
      "<div class=\"hint\">" + escapeHtml(card.explanation || card.detail || card.recommended_action) + "</div>";
  }
  function sourceLink(card) {
    var href = card.source_href || "";
    if (!href) return "";
    return "<a class=\"secondary\" href=\"" + escapeHtml(href) + "\">Open source</a>";
  }
  function cardActions(card) {
    var open = sourceLink(card);
    if (card.source_module === "link") {
      return "<div class=\"card-actions\">" + open + "</div>";
    }
    var review = card.action_id
      ? "<button type=\"button\" class=\"secondary\" data-review=\"" + escapeHtml(card.action_id) + "\">Review</button>"
      : "";
    if (card.action_id && card.status === "proposed") {
      var draft = card.recommended_action === "create_draft"
        ? "<button type=\"button\" data-approve=\"" + escapeHtml(card.action_id) + "\">Prepare draft</button>"
        : (card.recommended_action === "acknowledge"
          ? "<button type=\"button\" data-approve=\"" + escapeHtml(card.action_id) + "\">Acknowledge</button>"
          : "<button type=\"button\" data-approve=\"" + escapeHtml(card.action_id) + "\">Approve</button>");
      return "<div class=\"card-actions\">" +
        draft +
        "<button type=\"button\" class=\"secondary\" data-snooze=\"" + escapeHtml(card.action_id) + "\">Snooze 24h</button>" +
        "<button type=\"button\" class=\"secondary\" data-dismiss=\"" + escapeHtml(card.action_id) + "\">Dismiss</button>" +
        review + open +
        "</div>";
    }
    return "<div class=\"card-actions\">" + review + open + "</div>";
  }
  function cardHtml(card) {
    return "<article class=\"item\">" +
      "<span class=\"trust\">" + escapeHtml(card.trust_label) + "</span>" +
      "<strong>" + escapeHtml(card.title) + "</strong>" +
      cardMeta(card) +
      cardActions(card) +
      "</article>";
  }
  function queueHtml(row) {
    return "<article class=\"item\">" +
      "<span class=\"trust\">ACTION REQUIRES APPROVAL</span>" +
      "<strong>" + escapeHtml(row.title) + "</strong>" +
      cardMeta(row) +
      "<div class=\"hint\">If approved: " + escapeHtml(row.if_approved || "") + "</div>" +
      "<div class=\"hint\">Will not happen: " + escapeHtml(row.will_not_happen || "") + "</div>" +
      "<div class=\"hint\">Why: " + escapeHtml(row.why_recommended || row.recommended_action) + "</div>" +
      cardActions(row) +
      "</article>";
  }
  function reviewHtml(row) {
    if (!row) return "No item selected.";
    var details = row.source_details || {};
    var history = (row.related_history || []).map(function (item) {
      return escapeHtml(item.result_type) + " · " + escapeHtml(item.title);
    }).join("<br>");
    return "<article class=\"item selected\">" +
      "<span class=\"trust\">" + escapeHtml(row.trust_label || "ACTION REQUIRES APPROVAL") + "</span>" +
      "<strong>" + escapeHtml(row.title) + "</strong>" +
      cardMeta(row) +
      "<div class=\"review-block\">Why Nova surfaced it: " + escapeHtml(row.why_surfaced || row.why_recommended || "") + "</div>" +
      "<div class=\"review-block\">What Nova recommends: " + escapeHtml(row.recommended_action || "") + "</div>" +
      "<div class=\"review-block\">If approved: " + escapeHtml(row.if_approved || "") + "</div>" +
      "<div class=\"review-block\">Will not happen: " + escapeHtml(row.will_not_happen || "") + "</div>" +
      (details.title || details.subject ? "<div class=\"review-block\">Source details: " + escapeHtml(details.sender || "") + " " + escapeHtml(details.subject || details.title || "") + "</div>" : "") +
      (details.source || details.unread || details.important ? "<div class=\"review-block\">Mailbox state: " + escapeHtml([details.source, details.unread, details.important].filter(Boolean).join(" · ")) + "</div>" : "") +
      (details.received_at ? "<div class=\"review-block\">Received: " + escapeHtml(details.received_at) + "</div>" : "") +
      (row.verification_label ? "<div class=\"review-block\">Result verification: " + escapeHtml(row.verification_label) + "</div>" : "") +
      (history ? "<div class=\"review-block\">Related history:<br>" + history + "</div>" : "<div class=\"review-block\">Related history: none yet.</div>") +
      "<div class=\"card-actions\"><button type=\"button\" class=\"secondary\" data-recheck=\"" + escapeHtml(row.action_id || "") + "\">Re-check source</button></div>" +
      cardActions(row) +
      "</article>";
  }
  function activityHtml(row) {
    return "<article class=\"item\">" +
      "<span class=\"trust\">" + escapeHtml(row.result_type || row.resulting_status || "") + "</span>" +
      "<strong>" + escapeHtml(row.title) + "</strong>" +
      "<div class=\"meta\">" +
      "<span>Action: " + escapeHtml(row.action_id) + "</span>" +
      "<span>Source: " + escapeHtml(row.source_module) + " / " + escapeHtml(row.source_ref_id) + "</span>" +
      "<span>" + escapeHtml(row.prior_status || "proposed") + " → " + escapeHtml(row.resulting_status || "") + "</span>" +
      (row.result_ref_id ? "<span>Result: " + escapeHtml(row.result_ref_id) + "</span>" : "") +
      (row.verification_label ? "<span>" + escapeHtml(row.verification_label) + "</span>" : "") +
      (row.prior_verification_status ? "<span>Was: " + escapeHtml(row.prior_verification_status) + "</span>" : "") +
      (row.decided_at ? "<span>" + escapeHtml(row.decided_at) + "</span>" : "") +
      "</div>" +
      (row.source_href ? "<div class=\"card-actions\"><a class=\"secondary\" href=\"" + escapeHtml(row.source_href) + "\">Open source</a></div>" : "") +
      "</article>";
  }
  function renderHealth(rows) {
    var host = $("source-health");
    if (!host) return;
    if (!rows || !rows.length) {
      host.textContent = "No source status yet.";
      return;
    }
    host.innerHTML = rows.map(function (row) {
      return "<span class=\"health-pill " + escapeHtml(row.status) + "\">" +
        escapeHtml(row.source) + ": " + escapeHtml(row.status) +
        (row.connector && row.connector !== "n/a" ? " · " + escapeHtml(row.connector) : "") +
        "</span>";
    }).join("");
  }
  function logicalKey(item) {
    return [item.source_module || "", item.source_ref_id || "", item.recommended_action || item.action_type || ""].join("|");
  }
  function dedupeLogical(items) {
    var seen = {};
    var kept = [];
    (items || []).forEach(function (item) {
      var key = logicalKey(item);
      if (!key || seen[key]) return;
      seen[key] = true;
      kept.push(item);
    });
    return kept;
  }
  function renderList(id, items, empty) {
    var unique = dedupeLogical(items);
    if (!unique || !unique.length) {
      $(id).innerHTML = empty;
      return;
    }
    $(id).innerHTML = unique.map(cardHtml).join("");
  }
  function renderProductCounts(cards) {
    var host = $("product-counts-box");
    if (!host) return;
    var specs = [
      { key: "health", label: "AMICOR Health", metric: "Active rides", href: "/workspace", open: "Open Health" },
      { key: "delivery", label: "AMICOR Delivery", metric: "Open requests", href: "/app", open: "Open Delivery" },
      { key: "freight", label: "AMICOR Nova Freight", metric: "Active shipments", href: "/nova/freight", open: "Open Freight" }
    ];
    var byKey = {};
    (cards || []).forEach(function (row) {
      if (row && row.key) byKey[row.key] = row;
    });
    host.innerHTML = specs.map(function (spec) {
      var row = byKey[spec.key] || {};
      var value = "Unavailable";
      if (row.status === "ok" && typeof row.count === "number") {
        value = String(row.count);
      }
      return "<article class=\"product-count-card\" data-count-key=\"" + escapeHtml(spec.key) + "\">" +
        "<span class=\"trust\">VERIFIED DATA</span>" +
        "<h3>" + escapeHtml(spec.label) + "</h3>" +
        "<p class=\"count-metric\">" + escapeHtml(spec.metric) + "</p>" +
        "<p class=\"count-value\">" + escapeHtml(value) + "</p>" +
        "<a class=\"secondary\" href=\"" + escapeHtml(spec.href) + "\">" + escapeHtml(spec.open) + "</a>" +
        "</article>";
    }).join("");
  }
  function moneyText(value) {
    var amount = Number(value);
    if (!isFinite(amount)) amount = 0;
    return amount.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }
  function workOpenLink() {
    return "<a class=\"secondary\" href=\"/nova/work\">Open Work dashboard</a>";
  }
  function renderWorkRevenueError() {
    var mode = $("work-mode");
    var host = $("work-revenue-box");
    if (mode) {
      mode.textContent = "Work & Revenue summary could not be loaded. Other Today sections are unchanged.";
    }
    if (!host) return;
    host.innerHTML = "<article class=\"product-count-card\">" +
      "<span class=\"trust\">ACTION REQUIRES APPROVAL</span>" +
      "<h3>Work &amp; Revenue</h3>" +
      "<p class=\"work-empty\">Work &amp; Revenue summary could not be loaded. Other Today sections are unchanged.</p>" +
      workOpenLink() +
      "</article>";
  }
  function renderWorkRevenue(summary) {
    var host = $("work-revenue-box");
    var mode = $("work-mode");
    if (!host) return;
    if (!summary) {
      renderWorkRevenueError();
      return;
    }
    var sources = summary.source_counts || {};
    var approvals = summary.approval_states || {};
    var revenue = summary.revenue_summary || {};
    var liveOff = summary.live_discovery_enabled !== true;
    var submitOff = summary.external_submission_enabled !== true;
    var financeOff = summary.financial_actions_enabled !== true;
    var modeParts = [];
    var diag = summary.discovery_diagnostics || {};
    if (liveOff) {
      modeParts.push("Opportunities are manual or simulated. Live discovery is disabled. Nova did not search the live internet.");
    } else {
      modeParts.push(
        "Live discovery is enabled (" +
        (diag.discovery_provider_label || diag.discovery_provider || "Remotive") +
        "). Recorded Today counts still separate manual/simulated from live results. Open Work & Revenue to run a search. External submission remains off."
      );
    }
    if (submitOff) modeParts.push("External submission is disabled. Approved is not submitted.");
    if (financeOff) modeParts.push("Financial execution is disabled. Nova cannot charge, invoice, or transfer money.");
    if (mode) mode.textContent = modeParts.join(" ");
    var total = Number(summary.work_opportunities || 0);
    var opportunityEmpty = total <= 0
      ? "<p class=\"work-empty\">No work opportunities recorded yet.</p>"
      : "";
    var waiting = Number(approvals.draft || 0) + Number(approvals.ready_for_review || 0);
    var approvalEmpty = waiting <= 0
      ? "<p class=\"work-empty\">No owner approvals waiting.</p>"
      : "";
    var engagements = Number(summary.active_engagements || 0);
    var tasks = Number(summary.active_tasks || 0);
    var activeEmpty = engagements <= 0 && tasks <= 0
      ? "<p class=\"work-empty\">No active managed work.</p>"
      : "";
    var received = Number(revenue.owner_confirmed_received || 0);
    var receivedEmpty = received <= 0
      ? "<p class=\"work-empty\">No received revenue recorded.</p>"
      : "";
    host.innerHTML =
      "<article class=\"product-count-card\" data-work-card=\"opportunities\">" +
        "<span class=\"trust\">USER-SAVED INFORMATION</span>" +
        "<h3>Work Opportunities</h3>" +
        "<p class=\"count-metric\">Recorded opportunities</p>" +
        "<p class=\"count-value\">" + escapeHtml(String(total)) + "</p>" +
        "<ul class=\"work-state-list\">" +
          "<li><span class=\"state-label\">MANUAL</span> " + escapeHtml(String(sources.manual || 0)) + "</li>" +
          "<li><span class=\"state-label\">SIMULATED / TEST</span> " + escapeHtml(String(sources.simulated || 0)) + "</li>" +
          "<li><span class=\"state-label\">LIVE DISCOVERED</span> " + escapeHtml(String(sources.live || 0)) + "</li>" +
        "</ul>" +
        opportunityEmpty +
        "<p class=\"hint\">Manual and simulated counts are never treated as live job-board results. Live discovered rows appear only after an owner runs discovery in Work &amp; Revenue.</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"approvals\">" +
        "<span class=\"trust\">ACTION REQUIRES APPROVAL</span>" +
        "<h3>Owner Approvals</h3>" +
        "<p class=\"count-metric\">Application review states</p>" +
        "<p class=\"count-value\">" + escapeHtml(String(waiting)) + " waiting</p>" +
        "<ul class=\"work-state-list\">" +
          "<li><span class=\"state-label\">DRAFT</span> " + escapeHtml(String(approvals.draft || 0)) + "</li>" +
          "<li><span class=\"state-label\">READY FOR REVIEW</span> " + escapeHtml(String(approvals.ready_for_review || 0)) + "</li>" +
          "<li><span class=\"state-label\">APPROVED</span> " + escapeHtml(String(approvals.approved || 0)) + " — future submission only</li>" +
          "<li><span class=\"state-label\">SUBMITTED</span> " + escapeHtml(String(approvals.submitted || 0)) + " — owner-recorded only</li>" +
        "</ul>" +
        approvalEmpty +
        "<p class=\"hint\">APPROVED is not SUBMITTED. Nova cannot send an external application from Today.</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"active-work\">" +
        "<span class=\"trust\">VERIFIED DATA</span>" +
        "<h3>Active Work</h3>" +
        "<p class=\"count-metric\">Internal managed-work tracking</p>" +
        "<p class=\"count-value\">" + escapeHtml(String(engagements)) + "</p>" +
        "<ul class=\"work-state-list\">" +
          "<li><span class=\"state-label\">ENGAGEMENTS</span> " + escapeHtml(String(engagements)) + "</li>" +
          "<li><span class=\"state-label\">OPEN TASKS</span> " + escapeHtml(String(tasks)) + "</li>" +
        "</ul>" +
        activeEmpty +
        "<p class=\"hint\">Internal tracking only. An engagement is not an external contract unless a stored record says so.</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"revenue\">" +
        "<span class=\"trust\">VERIFIED DATA</span>" +
        "<h3>Revenue</h3>" +
        "<p class=\"count-metric\">Separated owner-entered amounts</p>" +
        "<ul class=\"work-state-list\">" +
          "<li><span class=\"state-label\">ESTIMATED</span> " + escapeHtml(moneyText(revenue.estimated_pipeline)) + " — AMICOR ledger, not money earned</li>" +
          "<li><span class=\"state-label\">CONTRACTED</span> " + escapeHtml(moneyText(revenue.contracted_value)) + " — AMICOR ledger, not money earned</li>" +
          "<li><span class=\"state-label\">RECEIVED</span> " + escapeHtml(moneyText(revenue.owner_confirmed_received)) + " — AMICOR owner-confirmed only</li>" +
        "</ul>" +
        receivedEmpty +
        "<p class=\"hint\">" + escapeHtml(summary.revenue_disclaimer || "Estimated pipeline is not received revenue. Nova does not collect payment.") + "</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"owner-actions\">" +
        "<span class=\"trust\">ACTION REQUIRES APPROVAL</span>" +
        "<h3>Owner Actions</h3>" +
        "<p class=\"count-metric\">Open owner-required items</p>" +
        "<p class=\"count-value\">" + escapeHtml(String(summary.owner_action_required || 0)) + "</p>" +
        "<p class=\"hint\">Nova does not complete CAPTCHA, login, signature, or payment steps.</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"tasks-due\">" +
        "<span class=\"trust\">VERIFIED DATA</span>" +
        "<h3>Tasks Due</h3>" +
        "<p class=\"count-metric\">Internal tasks still open</p>" +
        "<p class=\"count-value\">" + escapeHtml(String(summary.tasks_due || 0)) + "</p>" +
        "<p class=\"hint\">Internal tracking only. Nova does not contact the client.</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"deliverables\">" +
        "<span class=\"trust\">VERIFIED DATA</span>" +
        "<h3>Deliverables</h3>" +
        "<p class=\"count-metric\">Pending owner-confirmed delivery</p>" +
        "<p class=\"count-value\">" + escapeHtml(String(summary.deliverables_pending || 0)) + "</p>" +
        "<p class=\"hint\">Delivered requires owner confirmation. Nova does not transmit files externally.</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"pipeline\">" +
        "<span class=\"trust\">VERIFIED DATA</span>" +
        "<h3>Revenue Pipeline</h3>" +
        "<p class=\"count-metric\">Quoted vs contracted vs received</p>" +
        "<ul class=\"work-state-list\">" +
          "<li><span class=\"state-label\">QUOTED</span> " + escapeHtml(moneyText(summary.quoted_pipeline)) + " — AMICOR ledger, not money earned</li>" +
          "<li><span class=\"state-label\">CONTRACTED REVENUE</span> " + escapeHtml(moneyText(summary.contracted_revenue || revenue.contracted_value)) + " — AMICOR ledger, not cash received</li>" +
          "<li><span class=\"state-label\">RECEIVED REVENUE</span> " + escapeHtml(moneyText(revenue.owner_confirmed_received)) + " — AMICOR owner-confirmed only</li>" +
        "</ul>" +
        "<p class=\"hint\">Quoted is not contracted. Contracted is not invoiced. Invoiced is not received.</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"recurring\">" +
        "<span class=\"trust\">VERIFIED DATA</span>" +
        "<h3>Recurring Work</h3>" +
        "<p class=\"count-metric\">Overdue internal series</p>" +
        "<p class=\"count-value\">" + escapeHtml(String(summary.recurring_overdue || 0)) + "</p>" +
        "<p class=\"hint\">Internal recurrence only. Nova does not send reminders or create calendars.</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"reports\">" +
        "<span class=\"trust\">ACTION REQUIRES APPROVAL</span>" +
        "<h3>Reports Awaiting Review</h3>" +
        "<p class=\"count-metric\">Internal weekly drafts</p>" +
        "<p class=\"count-value\">" + escapeHtml(String(summary.reports_awaiting_review || 0)) + "</p>" +
        "<p class=\"hint\">Generating a report is not sending it. There is no Send control on Today.</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"invoice-support\">" +
        "<span class=\"trust\">ACTION REQUIRES APPROVAL</span>" +
        "<h3>Invoice-support drafts</h3>" +
        "<p class=\"count-metric\">Internal invoice preparation</p>" +
        "<p class=\"count-value\">" + escapeHtml(String(summary.invoice_support_drafts || 0)) + "</p>" +
        "<p class=\"hint\">Not a Stripe invoice. Approval does not charge or send.</p>" +
        workOpenLink() +
      "</article>" +
      "<article class=\"product-count-card\" data-work-card=\"blocked\">" +
        "<span class=\"trust\">ACTION REQUIRES APPROVAL</span>" +
        "<h3>Blocked Work</h3>" +
        "<p class=\"count-metric\">Internal blocked or owner-action queue</p>" +
        "<p class=\"count-value\">" + escapeHtml(String(summary.blocked_work || 0)) + "</p>" +
        "<p class=\"hint\">Internal status only. Nova does not message the client.</p>" +
        workOpenLink() +
      "</article>";
  }
  async function loadWorkRevenue() {
    if (!$("work-revenue-box")) return;
    if (!token()) {
      if ($("work-mode")) $("work-mode").textContent = "Sign in to load Work & Revenue mode.";
      return;
    }
    try {
      var summary = await api("/api/nova/work/today-summary");
      var workRevenuePanel = document.querySelector('[aria-label="Work and Revenue"]');
      if (workRevenuePanel) workRevenuePanel.classList.remove("hidden");
      renderWorkRevenue(summary);
    } catch (_) {
      var workRevenuePanel = document.querySelector('[aria-label="Work and Revenue"]');
      if (workRevenuePanel) workRevenuePanel.classList.add("hidden");
    }
  }
  async function applyProductAccess() {
    if (!token()) return;
    try {
      var access = await api("/api/nova/signup/me/access");
      var isCustomer = !!(access && access.nova_saas_customer);
      var currentIdentity = identity();
      document.querySelectorAll(".today-nav a").forEach(function (el) {
        var href = el.getAttribute("href") || "";
        if (
          href === "/workspace" ||
          href === "/app" ||
          href === "/nova/freight" ||
          href === "/nova/payments/readiness"
        ) {
          el.classList.toggle("hidden", isCustomer);
        }
      });
      var linkedPanel = document.querySelector('[aria-label="Health, Delivery, and Freight"]');
      if (linkedPanel) linkedPanel.classList.toggle("hidden", isCustomer);
      var productLinksPanel = document.querySelector('[aria-label="Product links"]');
      if (productLinksPanel) productLinksPanel.classList.toggle("hidden", isCustomer);
      var workRevenuePanel = document.querySelector('[aria-label="Work and Revenue"]');
      if (workRevenuePanel && isCustomer) workRevenuePanel.classList.add("hidden");
    } catch (_) {}
  }

  async function refresh() {
    if (!token()) {
      $("brain-output").textContent = "Mrs. Nova Brain is ready when you are signed in.";
      setSignedIn(false);
      return;
    }
    var dash = await api("/api/nova/today/dashboard");
    setSignedIn(true);
    if ($("brain-output") && String($("brain-output").textContent || "").indexOf("when you are signed in") !== -1) {
      $("brain-output").textContent = "Mrs. Nova Brain is ready. Ask a question below.";
    }
    await applyProductAccess();
    renderList("attention-box", dash.attention_now, "Nothing needs attention now. No real items were invented.");
    renderList("communications-box", dash.communications, "No real unread or important communications.");
    renderList("government-box", dash.government, "No saved government or compliance items.");
    renderList("business-box", dash.business, "No saved business or operations follow-ups.");
    renderList("workspace-box", dash.workspace, "No recent workspace work.");
    try {
      renderProductCounts(dash.product_counts);
    } catch (_) {
      renderProductCounts([]);
    }
    renderList("links-box", dash.product_links, "Product links unavailable.");
    renderList("recommendations-box", dash.recommendations, "No current recommendation because no saved record requires attention.");
    var queue = dedupeLogical(dash.approval_queue);
    $("queue-box").innerHTML = queue.length
      ? queue.map(queueHtml).join("")
      : "No items waiting for approval.";
    $("activity-box").innerHTML = (dash.recent_activity && dash.recent_activity.length)
      ? dash.recent_activity.map(activityHtml).join("")
      : "No recent owner activity.";
    renderHealth(dash.source_health);
    var connector = $("connector-health");
    if (connector) {
      var health = dash.connector_health || {};
      var parts = [];
      if (health.status === "not_configured") parts.push("Mailbox: not configured");
      else if (health.status) parts.push("Mailbox: " + health.status);
      if (health.provider) parts.push(health.provider);
      if (health.freshness) parts.push("Freshness: " + health.freshness);
      if (health.last_success_at) parts.push("Last successful read: " + health.last_success_at);
      if (health.last_attempted_at) parts.push("Last attempted read: " + health.last_attempted_at);
      if (health.recheck_available === "yes") parts.push("Manual re-check available");
      if (health.detail) parts.push(health.detail);
      connector.textContent = parts.length ? parts.join(" · ") : "No mailbox connector status.";
    }
    try {
      await loadWorkRevenue();
    } catch (_) {
      renderWorkRevenueError();
    }
    hideBanner();
    if (selectedActionId) {
      try {
        var selected = await api("/api/nova/today/actions/" + encodeURIComponent(selectedActionId));
        selectedSourceRefId = selected.source_ref_id || "";
        $("review-box").innerHTML = reviewHtml(selected);
      } catch (_) {
        $("review-box").innerHTML = "Selected item is no longer visible.";
      }
    }
  }
  function renderBrainSources(sources, fallbackHref) {
    var box = $("brain-sources");
    if (!box) return;
    var rows = Array.isArray(sources) ? sources.slice(0, 8) : [];
    if (!rows.length && fallbackHref) {
      rows = [{ title: "Open source", url: fallbackHref, label: "Source" }];
    }
    if (!rows.length) {
      box.innerHTML = "";
      box.classList.add("hidden");
      return;
    }
    box.innerHTML = rows.map(function (row, index) {
      var url = String(row.url || "");
      if (!/^https?:\/\//i.test(url)) return "";
      var title = escapeHtml(row.title || row.label || ("Source " + (index + 1)));
      var label = escapeHtml(row.label || "");
      return "<a class=\"brain-source-link\" href=\"" + escapeHtml(url) +
        "\" target=\"_blank\" rel=\"noopener noreferrer\">" +
        title + (label && label !== title ? " · " + label : "") + "</a>";
    }).join("");
    box.classList.toggle("hidden", !box.innerHTML);
  }

  async function runBrain(event) {
    event.preventDefault();
    if (!token()) {
      showBanner("Sign in to ask Mrs. Nova Brain.");
      $("login-form").classList.remove("hidden");
      return;
    }
    var question = $("ask-input").value.trim();
    if (!question) {
      showBanner("Type a question or use the microphone.");
      return;
    }
    var result = await api("/api/nova/today/ask", {
      method: "POST",
      body: JSON.stringify({
        question: question,
        action_id: selectedActionId || null,
        source_ref_id: selectedSourceRefId || null
      })
    });
    var answer = result.answer || "No response from Mrs. Nova Brain.";
    $("brain-output").textContent = (result.fact_label || "AI SUGGESTION") + "\n\n" + answer;
    renderBrainSources(result.sources || [], result.source_href || "");
    $("ask-input").value = "";
    $("ask-input").focus();
    speakNova(answer);
    showBanner("Mrs. Nova Brain answered. Nothing was sent or filed.", true);
    await refresh();
  }
  async function decide(actionId, kind) {
    var path = "/api/nova/today/actions/" + encodeURIComponent(actionId) + "/" + kind;
    var body = kind === "snooze" ? JSON.stringify({ hours: 24 }) : "{}";
    var result = await api(path, { method: "POST", body: body });
    if (kind === "approve" && result.href) {
      showBanner((result.message || "Approved.") + " Opened only after your confirmation.", true);
    } else if (kind === "snooze") {
      showBanner("Snoozed for 24 hours. It will return to Today after that.", true);
    } else {
      showBanner(result.message || "Saved. Refresh will keep this decision.", true);
    }
    await refresh();
  }
  async function recheckSource(actionId) {
    var result = await api("/api/nova/today/recheck", {
      method: "POST",
      body: JSON.stringify({ action_id: actionId || null })
    });
    showBanner((result.message || "Source re-checked.") + " Nothing was sent or recreated.", true);
    await refresh();
  }
  document.addEventListener("click", function (event) {
    var approve = event.target && event.target.getAttribute && event.target.getAttribute("data-approve");
    var snooze = event.target && event.target.getAttribute && event.target.getAttribute("data-snooze");
    var dismiss = event.target && event.target.getAttribute && event.target.getAttribute("data-dismiss");
    var review = event.target && event.target.getAttribute && event.target.getAttribute("data-review");
    var recheck = event.target && event.target.getAttribute && event.target.getAttribute("data-recheck");
    if (review) {
      selectedActionId = review;
      refresh().catch(function (err) { showBanner(err.message || String(err)); });
      $("ask-input").focus();
      return;
    }
    if (approve) {
      decide(approve, "approve").catch(function (err) { showBanner(err.message || String(err)); });
    }
    if (snooze) {
      decide(snooze, "snooze").catch(function (err) { showBanner(err.message || String(err)); });
    }
    if (dismiss) {
      decide(dismiss, "dismiss").catch(function (err) { showBanner(err.message || String(err)); });
    }
    if (recheck) {
      recheckSource(recheck).catch(function (err) { showBanner(err.message || String(err)); });
    }
  });
  if ($("recheck-mailbox")) {
    $("recheck-mailbox").addEventListener("click", function () {
      recheckSource(null).catch(function (err) { showBanner(err.message || String(err)); });
    });
  }
  $("ask-form").addEventListener("submit", function (event) {
    runBrain(event).catch(function (err) { showBanner(err.message || String(err)); });
  });
  if ($("ask-mic")) {
    $("ask-mic").addEventListener("click", function () {
      startVoiceInput();
    });
  }
  if ($("stop-speaking")) {
    $("stop-speaking").addEventListener("click", function () {
      stopNovaSpeaking();
    });
  }
  $("sign-in-toggle").addEventListener("click", function () {
    $("login-form").classList.toggle("hidden");
  });
  $("sign-out").addEventListener("click", function () {
    if (session() && session().logout) {
      session().logout();
    }
    setSignedIn(false);
    if ($("work-mode")) $("work-mode").textContent = "Sign in to load Work & Revenue mode.";
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
  refresh().catch(function (err) {
    showBanner(err.message || String(err));
    loadWorkRevenue().catch(function () { renderWorkRevenueError(); });
  });
  applyProductAccess().catch(function () {});
})();
