(function () {
  var token = "";
  var snapshot = {};

  function $(id) {
    return document.getElementById(id);
  }

  function headers() {
    return token ? { Authorization: "Bearer " + token, "Content-Type": "application/json" } : { "Content-Type": "application/json" };
  }

  function fill(id, value) {
    var node = $(id);
    if (!node) return;
    node.textContent = JSON.stringify(value, null, 2);
  }

  function firstId(rows, key) {
    if (!rows || !rows.length) return "";
    return rows[0][key] || "";
  }

  async function verifyOwnerAccess() {
    var response = await fetch("/api/nova/v3/owner-access", { headers: headers() });
    if (!response.ok) {
      $("session").textContent = response.status === 403
        ? "Owner access required. This workspace is private."
        : "Owner authorization check failed: " + response.status;
      token = "";
      document.body.classList.add("owner-gate-pending");
      return false;
    }
    document.body.classList.remove("owner-gate-pending");
    return true;
  }

  async function loadLab() {
    var response = await fetch("/api/nova/v3/lab", { headers: headers() });
    if (!response.ok) {
      $("session").textContent = "Lab load failed: " + response.status;
      return;
    }
    var data = await response.json();
    snapshot = data;
    ["opportunities", "applications", "clients", "engagements", "tasks", "active_work", "deliverables", "approvals", "communications", "invoices", "payments", "workers", "connectors", "alerts", "audit", "growth", "shield"].forEach(function (key) {
      fill(key, data[key] || []);
    });
    var crm = data.growth_crm || {};
    fill("new_leads", crm["NEW LEADS"] || []);
    fill("qualified", crm["QUALIFIED"] || []);
    fill("owner_review", crm["NEEDS OWNER REVIEW"] || []);
    fill("outreach_ready", crm["OUTREACH READY"] || []);
    fill("follow_up", crm["FOLLOW-UP"] || []);
    fill("do_not_contact", crm["DO NOT CONTACT"] || []);
    fill("customers_converted", (data.growth && data.growth.CUSTOMERS_CONVERTED) || crm["CUSTOMERS CONVERTED"] || []);
    var counts = $("counts");
    counts.innerHTML = "";
    [
      ["OPPORTUNITIES", (data.opportunities || []).length],
      ["CLIENTS", (data.clients || []).length],
      ["APPLICATIONS", (data.applications || []).length],
      ["ENGAGEMENTS", (data.engagements || []).length],
      ["TASKS", (data.tasks || []).length],
      ["DELIVERABLES", (data.deliverables || []).length],
      ["APPROVALS", (data.approvals || []).length],
      ["COMMUNICATIONS", (data.communications || []).length],
      ["INVOICES", (data.invoices || []).length],
      ["PAYMENTS", (data.payments || []).length],
      ["WORKERS", (data.workers || []).length],
      ["CONNECTORS", Array.isArray(data.connectors) ? data.connectors.length : 0],
      ["LEADS FOUND", (data.growth && data.growth["LEADS FOUND"]) || 0],
      ["CUSTOMERS CONVERTED", ((data.growth && data.growth.CUSTOMERS_CONVERTED) || []).length],
      ["BLOCKED BY SHIELD", (data.growth && data.growth["BLOCKED BY SHIELD"]) || 0],
      ["ALERTS", data.alerts ? 1 : 0],
      ["AUDIT", (data.audit || []).length]
    ].forEach(function (row) {
      var card = document.createElement("div");
      card.innerHTML = "<strong>" + row[0] + "</strong><div>" + row[1] + "</div>";
      counts.appendChild(card);
    });
    $("session").textContent = "Synthetic lab loaded. Live flags remain off.";
  }

  function payloadFor(action) {
    var opportunityId = firstId(snapshot.opportunities, "opportunity_id");
    var proposalId = firstId(snapshot.applications, "proposal_id");
    var engagementId = firstId(snapshot.engagements, "engagement_id");
    var workId = firstId(snapshot.tasks, "work_item_id") || firstId(snapshot.active_work, "work_item_id");
    var invoiceId = firstId(snapshot.invoices, "invoice_id");
    var jobId = firstId(snapshot.workers, "job_id");
    var approvalId = firstId(snapshot.approvals, "approval_id");
    var expected = (snapshot.engagements && snapshot.engagements[0] && snapshot.engagements[0].expected_amount) || 1000;
    var map = {
      approve_opportunity: { opportunity_id: opportunityId },
      reject_opportunity: { opportunity_id: opportunityId },
      prepare_proposal: { opportunity_id: opportunityId },
      approve_proposal: { proposal_id: proposalId },
      mock_submit: { proposal_id: proposalId },
      create_engagement: { proposal_id: proposalId },
      create_task: { engagement_id: engagementId, work_type: "administrative_reporting", source_inputs: { notes: "lab" } },
      complete_synthetic_task: { work_item_id: workId },
      prepare_deliverable: { work_item_id: workId },
      approve_deliverable: { work_item_id: workId },
      mock_deliver: { work_item_id: workId },
      generate_invoice: { engagement_id: engagementId, amount: expected, kind: "fixed" },
      approve_invoice: { invoice_id: invoiceId },
      mock_send_invoice: { invoice_id: invoiceId },
      record_synthetic_partial_payment: { engagement_id: engagementId, amount: expected * 0.4 },
      record_synthetic_final_payment: { engagement_id: engagementId, amount: expected },
      pause_worker: { job_id: jobId },
      resume_worker: { job_id: jobId },
      retry_failed_worker: { job_id: jobId },
      revoke_approval: { approval_id: approvalId },
      archive_engagement: { engagement_id: engagementId }
    };
    return map[action] || {};
  }

  async function runAction(action) {
    $("action-status").textContent = "Running " + action + "…";
    try {
      if (action === "ingest") {
        var ingest = await fetch("/api/nova/v3/ingest", {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({ provider_id: "synthetic_job_board" })
        });
        $("action-status").textContent = ingest.ok ? "Ingested synthetic opportunities." : "Ingest failed: " + ingest.status;
        await loadLab();
        return;
      }
      if (action === "tick_worker") {
        var tick = await fetch("/api/nova/v3/workers/tick", {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({ worker_id: "lab-worker" })
        });
        $("action-status").textContent = tick.ok ? "Synthetic worker tick complete." : "Tick failed: " + tick.status;
        await loadLab();
        return;
      }
      if (action === "growth_discover") {
        var created = await fetch("/api/nova/v3/growth/leads", {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({
            organization_name: "Lab SMB",
            contact_name: "Owner",
            role_title: "Owner",
            industry: "professional services",
            geography: "remote",
            email_placeholder: "owner@example-smb.test",
            business_need: "administrative automation",
            product_fit: "nova",
            estimated_value: 299,
            source: "synthetic_lab"
          })
        });
        $("action-status").textContent = created.ok ? "Synthetic lead discovered." : "Lead discover failed: " + created.status;
        await loadLab();
        return;
      }
      if (action === "growth_qualify") {
        var leadId = firstId(snapshot.growth_leads, "lead_id");
        var q = await fetch("/api/nova/v3/growth/leads/" + leadId + "/qualify", { method: "POST", headers: headers(), body: "{}" });
        $("action-status").textContent = q.ok ? "Lead qualified." : "Qualify failed: " + q.status;
        await loadLab();
        return;
      }
      if (action === "growth_outreach") {
        var outreachLead = firstId(snapshot.growth_leads, "lead_id");
        var o = await fetch("/api/nova/v3/growth/outreach", {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({ lead_id: outreachLead, kind: "introduction_email" })
        });
        $("action-status").textContent = o.ok ? "Outreach drafted (mock)." : "Outreach blocked: " + o.status;
        await loadLab();
        return;
      }
      if (action === "growth_synthetic_convert") {
        var converted = await fetch("/api/nova/v3/lab/action", {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({ action: "growth_synthetic_convert", payload: { organization_name: "Convert Co" } })
        });
        $("action-status").textContent = converted.ok ? "Synthetic customer converted (mock)." : "Convert failed: " + converted.status;
        await loadLab();
        return;
      }
      var response = await fetch("/api/nova/v3/lab/action", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ action: action, payload: payloadFor(action) })
      });
      var body = await response.json().catch(function () { return {}; });
      if (!response.ok) {
        $("action-status").textContent = "Blocked: " + ((body.detail && body.detail.code) || response.status);
      } else {
        $("action-status").textContent = "Completed " + action + " (synthetic).";
      }
      await loadLab();
    } catch (err) {
      $("action-status").textContent = "Action failed.";
    }
  }

  document.querySelectorAll("[data-action]").forEach(function (button) {
    button.addEventListener("click", function () {
      runAction(button.getAttribute("data-action"));
    });
  });

  $("login-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: $("email").value, password: $("password").value })
    });
    if (!response.ok) {
      $("session").textContent = "Sign in failed.";
      return;
    }
    token = (await response.json()).access_token;
    if (await verifyOwnerAccess()) {
      await loadLab();
    }
  });
})();
