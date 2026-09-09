"use strict";

(function () {
  var state = { customerId: null, opportunityId: null };

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
    return String(value || "")
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
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · Mrs. Nova Brain"
      : "Sign in to use Nova Business.";
  }
  function renderDashboard(data) {
    var pipe = data.pipeline || {};
    $("pipeline-box").innerHTML = "<strong>Open " + escapeHtml(pipe.open_pipeline) +
      "</strong><div class=\"muted\">Expected " + escapeHtml(pipe.expected_revenue) +
      " · Won " + escapeHtml(pipe.won_pipeline) + "</div><div class=\"muted\">" +
      escapeHtml(pipe.disclaimer || "Operational forecasting only.") + "</div>";
    $("opp-list").innerHTML = listHtml(data.open_opportunities, "No open opportunities.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.title) + "</strong><div class=\"muted\">" +
        escapeHtml(row.status) + " · " + escapeHtml(row.estimated_value) + "</div></div>";
    });
    $("customer-list").innerHTML = listHtml(data.active_customers, "No active customers.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.name) + "</strong><div class=\"muted\">" +
        escapeHtml(row.kind) + " · " + escapeHtml(row.status) + "</div></div>";
    });
    $("follow-list").innerHTML = listHtml(data.follow_ups_due, "No follow-ups due.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.name) + "<div class=\"muted\">" +
        escapeHtml(row.next_follow_up) + "</div></div>";
    });
    $("task-list").innerHTML = listHtml(data.overdue_tasks, "No overdue tasks.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.title) + "<div class=\"muted\">Due " +
        escapeHtml(row.due_date) + "</div></div>";
    });
    $("meeting-list").innerHTML = listHtml(data.upcoming_meetings, "No upcoming meetings.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.title) + "<div class=\"muted\">" +
        escapeHtml(row.start_time) + "</div></div>";
    });
    $("doc-list").innerHTML = listHtml(data.documents_attention, "No documents needing attention.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.title) + "<div class=\"muted\">" +
        escapeHtml(row.kind) + " · " + escapeHtml(row.expiration_date || row.status) + "</div></div>";
    });
    $("expense-box").innerHTML = "<strong>" + escapeHtml(data.expense_total) +
      "</strong><div class=\"muted\">" + escapeHtml(data.expense_label) + "</div>";
    $("gov-list").innerHTML = listHtml(data.government_items, "No Government Hub items referenced.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.title) + "<div class=\"muted\">" +
        escapeHtml(row.status) + " · " + escapeHtml(row.item_id) + "</div></div>";
    });
    $("comms-list").innerHTML = listHtml(data.communications_recent, "No recent Communications activity.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.title) + "<div class=\"muted\">" +
        escapeHtml(row.sender || "") + "</div></div>";
    });
    $("vendor-list").innerHTML = listHtml(data.vendors, "No vendors.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.vendor_name) + "<div class=\"muted\">" +
        escapeHtml(row.status) + "</div></div>";
    });
    $("activity-list").innerHTML = listHtml(data.recent_activity, "No recent activity.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.title) + "<div class=\"muted\">" +
        escapeHtml(row.kind) + "</div></div>";
    });
  }
  async function refresh() {
    if (!token()) {
      setSignedIn(false);
      $("brain-output").textContent = "Mrs. Nova Brain is ready when you are signed in.";
      return;
    }
    setSignedIn(true);
    renderDashboard(await api("/api/nova/business/dashboard"));
    $("brain-output").textContent = "Mrs. Nova Brain is connected to Nova Business OS. AI SUGGESTION is not an official ruling or ledger entry.";
  }
  async function runBrain(action) {
    if (!token()) {
      showBanner("Sign in to ask Mrs. Nova Brain.");
      $("login-form").classList.remove("hidden");
      return;
    }
    var result = await api("/api/nova/business/ask", {
      method: "POST",
      body: JSON.stringify({
        action: action,
        question: $("ask-input").value.trim(),
        customer_id: state.customerId,
        opportunity_id: state.opportunityId
      })
    });
    $("brain-output").textContent = (result.fact_label || "AI SUGGESTION") + "\n\n" + (result.answer || "No response.");
    $("fact-label").textContent = result.fact_label || "AI SUGGESTION is not accounting or a filing.";
    showBanner("Mrs. Nova Brain used existing Nova intelligence. Nothing was sent or booked.", true);
    await refresh();
  }

  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message); });

  $("ask-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try { await runBrain("ask"); } catch (err) { showBanner(err.message); }
  });
  document.querySelectorAll("[data-brain]").forEach(function (button) {
    button.addEventListener("click", async function () {
      try { await runBrain(button.getAttribute("data-brain")); } catch (err) { showBanner(err.message); }
    });
  });
  $("profile-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      await api("/api/nova/business/profiles", {
        method: "POST",
        body: JSON.stringify({
          business_name: $("profile-name").value,
          legal_name: $("profile-legal").value || null,
          entity_type: $("profile-entity").value,
          state_of_formation: $("profile-state").value || null,
          workspace_id: $("profile-workspace").value || null,
          government_item_id: $("profile-gov").value || null
        })
      });
      showBanner("Business profile saved as USER-SAVED INFORMATION.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("customer-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      var created = await api("/api/nova/business/customers", {
        method: "POST",
        body: JSON.stringify({
          name: $("customer-name").value,
          kind: $("customer-kind").value,
          email: $("customer-email").value || null,
          next_follow_up: $("customer-follow").value || null
        })
      });
      state.customerId = created.customer_id;
      showBanner("Customer saved. Communications contacts were referenced, not duplicated as a second engine.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("opp-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      var created = await api("/api/nova/business/opportunities", {
        method: "POST",
        body: JSON.stringify({
          title: $("opp-title").value,
          estimated_value: Number($("opp-value").value || 0),
          probability: Number($("opp-prob").value || 0),
          status: $("opp-status").value,
          customer_id: $("opp-customer").value || state.customerId || null
        })
      });
      state.opportunityId = created.opportunity_id;
      showBanner("Opportunity saved. This is operational forecasting, not booked revenue.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("task-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      await api("/api/nova/business/tasks", {
        method: "POST",
        body: JSON.stringify({
          title: $("task-title").value,
          due_date: $("task-due").value || null,
          government_item_id: $("task-gov").value || null,
          customer_id: state.customerId,
          opportunity_id: state.opportunityId
        })
      });
      showBanner("Task saved.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("vendor-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      await api("/api/nova/business/vendors", {
        method: "POST",
        body: JSON.stringify({ vendor_name: $("vendor-name").value, category: $("vendor-category").value || null })
      });
      showBanner("Vendor saved. No procurement automation.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("doc-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      await api("/api/nova/business/documents", {
        method: "POST",
        body: JSON.stringify({
          title: $("doc-title").value,
          kind: $("doc-kind").value,
          expiration_date: $("doc-exp").value || null,
          file_id: $("doc-file").value || null,
          customer_id: state.customerId
        })
      });
      showBanner("Document link saved. Files stay in Nova Workspace.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("expense-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      await api("/api/nova/business/expenses", {
        method: "POST",
        body: JSON.stringify({
          amount: Number($("expense-amount").value || 0),
          vendor_name: $("expense-vendor").value || null,
          description: $("expense-desc").value
        })
      });
      showBanner("Operational Expense Tracking — NOT Accounting.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("meeting-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      await api("/api/nova/business/meetings", {
        method: "POST",
        body: JSON.stringify({
          title: $("meeting-title").value,
          start_time: new Date($("meeting-start").value).toISOString(),
          customer_id: state.customerId,
          opportunity_id: state.opportunityId,
          create_follow_up_task: true
        })
      });
      showBanner("Local meeting saved through Communications calendar. Health appointments were not changed.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("draft-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      await api("/api/nova/business/draft", {
        method: "POST",
        body: JSON.stringify({
          to: $("draft-to").value ? [$("draft-to").value] : [],
          subject: $("draft-subject").value,
          body: "Draft only. Nothing was sent.",
          customer_id: state.customerId,
          opportunity_id: state.opportunityId
        })
      });
      showBanner("Draft saved in Nova Communications. Nothing was sent.", true);
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
    showBanner("Signed in. Nova Business OS is available.", true);
  });
  $("sign-out").addEventListener("click", async function () {
    if (session() && session().logout) await session().logout();
    window.location.href = "/nova/business";
  });
})();
