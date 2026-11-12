(() => {
  const state = {
    token: localStorage.getItem("amicor_growth_token") || "",
    conversationId: null,
    workflowRunId: null,
  };

  const $ = (id) => document.getElementById(id);
  const banner = $("status-banner");
  const sessionMeta = $("session-meta");

  function setBanner(text, kind = "warn") {
    banner.className = `banner ${kind}`;
    banner.textContent = text;
  }

  function authHeaders() {
    const headers = { "Content-Type": "application/json" };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    return headers;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: { ...authHeaders(), ...(options.headers || {}) },
    });
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { raw: text };
    }
    if (!res.ok) {
      const detail = data.detail || data.message || data.error || res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  async function login(email, password) {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    state.token = data.access_token || data.token || "";
    if (!state.token) throw new Error("No access token returned");
    localStorage.setItem("amicor_growth_token", state.token);
    sessionMeta.textContent = `Signed in as ${email}`;
    setBanner("Signed in. Growth Agent APIs require NOVA_GROWTH_AGENT_ENABLED=true.", "ok");
    await refreshAll();
  }

  function signOut() {
    state.token = "";
    localStorage.removeItem("amicor_growth_token");
    sessionMeta.textContent = "Signed out.";
    setBanner("Sign in required. Metrics, diagnostics, CRM, and booking need an owner session.", "warn");
    $("metrics").innerHTML = `<div class="hint">Sign in to load metrics. Live delivery remains off.</div>`;
    $("inbox").textContent = "Sign in to load conversations.";
    $("inbox").className = "empty";
    $("leads").textContent = "Sign in to load leads.";
    $("leads").className = "empty";
    $("diagnostics-out").textContent = "";
    if ($("diagnostics-flags")) $("diagnostics-flags").textContent = "";
  }

  function requireSession() {
    if (!state.token) {
      throw new Error("Sign in required before using owner controls.");
    }
  }

  function parseJsonField(id, label) {
    const raw = $(id).value.trim() || (id.includes("faqs") || id.includes("services") ? "[]" : "{}");
    try {
      return JSON.parse(raw);
    } catch {
      throw new Error(`${label} must be valid JSON`);
    }
  }

  function setupPayload(extra = {}) {
    return {
      business_name: $("biz-name").value.trim(),
      is_synthetic_demo: $("biz-synthetic").checked,
      website: $("biz-web").value.trim() || null,
      timezone: $("biz-tz").value,
      plan_code: $("biz-plan").value,
      contact_email: $("biz-email").value.trim() || null,
      handoff_phone: $("biz-phone").value.trim() || null,
      operating_hours: parseJsonField("biz-hours", "Operating hours"),
      services: parseJsonField("biz-services", "Services"),
      faqs: parseJsonField("biz-faqs", "FAQs"),
      escalation_settings: { handoff_on_unknown: true },
      quiet_hours: { enabled: true, start: "21:00", end: "08:00" },
      ...extra,
    };
  }

  async function refreshMetrics() {
    const box = $("metrics");
    if (!state.token) {
      box.innerHTML = `<div class="hint">Sign in to load metrics. Live delivery remains off.</div>`;
      return;
    }
    box.innerHTML = `<div class="loading">Loading metrics…</div>`;
    try {
      const data = await api("/api/nova/growth-agent/analytics?days=30");
      box.innerHTML = [
        ["Inquiries", data.inquiries],
        ["Consented leads", data.consented_leads],
        ["Booked", data.booked_appointments],
        ["Delivery ok", data.delivery_success],
        ["Delivery fail/suppress", data.delivery_failure_or_suppressed],
        ["Opt-outs", data.opt_outs],
        ["Cost est. USD", data.usage_cost_estimate_usd],
      ]
        .map(
          ([label, value]) =>
            `<div class="metric"><strong>${value ?? "—"}</strong><span>${label}</span></div>`
        )
        .join("");
      box.insertAdjacentHTML(
        "beforeend",
        `<p class="hint" style="grid-column:1/-1">${data.denominator_note || ""} Billed: ${data.billed}</p>`
      );
    } catch (err) {
      box.innerHTML = `<div class="error">${err.message}</div>`;
    }
  }

  async function refreshInbox() {
    const box = $("inbox");
    try {
      const data = await api("/api/nova/growth-agent/conversations");
      const rows = data.conversations || [];
      if (!rows.length) {
        box.className = "empty";
        box.textContent = "No conversations yet.";
        return;
      }
      box.className = "";
      box.innerHTML = `<table class="table"><thead><tr><th>Subject</th><th>Handler</th><th>Status</th><th></th></tr></thead><tbody>${rows
        .map(
          (c) => `<tr>
            <td>${escapeHtml(c.subject || c.id)}${c.is_synthetic_demo ? ' <span class="tag demo">Synthetic</span>' : ""}</td>
            <td><span class="tag ${c.handler}">${c.handler}</span></td>
            <td>${escapeHtml(c.status)}</td>
            <td><button type="button" data-handoff="${c.id}" class="secondary">Handoff</button></td>
          </tr>`
        )
        .join("")}</tbody></table>`;
      box.querySelectorAll("[data-handoff]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await api(`/api/nova/growth-agent/conversations/${btn.dataset.handoff}/handoff`, {
            method: "POST",
            body: "{}",
          });
          await refreshInbox();
        });
      });
    } catch (err) {
      box.className = "error";
      box.textContent = err.message;
    }
  }

  async function refreshLeads() {
    const box = $("leads");
    const q = $("lead-search").value.trim();
    try {
      const data = await api(`/api/nova/growth-agent/leads${q ? `?q=${encodeURIComponent(q)}` : ""}`);
      const rows = data.leads || [];
      if (!rows.length) {
        box.className = "empty";
        box.textContent = "No leads yet.";
        return;
      }
      const states = ["new", "contacted", "qualified", "booked", "closed"];
      box.className = "";
      box.innerHTML = `<table class="table"><thead><tr><th>Name</th><th>State</th><th>Notes</th><th>Demo</th><th></th></tr></thead><tbody>${rows
        .map((l) => {
          const stateOpts = states
            .map(
              (s) =>
                `<option value="${s}" ${s === l.lead_state ? "selected" : ""}>${s}</option>`
            )
            .join("");
          return `<tr data-lead-id="${escapeHtml(l.id)}">
            <td>${escapeHtml(l.display_name || l.id)}</td>
            <td><select aria-label="Lead state" data-lead-state>${stateOpts}</select></td>
            <td><input type="text" aria-label="Lead notes" data-lead-notes value="${escapeHtml(
              l.notes || ""
            )}" /></td>
            <td>${l.is_synthetic_demo ? '<span class="tag demo">Synthetic</span>' : ""}</td>
            <td><button type="button" class="secondary" data-save-lead>Save</button></td>
          </tr>`;
        })
        .join("")}</tbody></table>`;
      box.querySelectorAll("[data-save-lead]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const row = btn.closest("tr");
          const id = row?.dataset.leadId;
          if (!id) return;
          const leadState = row.querySelector("[data-lead-state]")?.value;
          const notes = row.querySelector("[data-lead-notes]")?.value || "";
          try {
            await api(`/api/nova/growth-agent/leads/${encodeURIComponent(id)}`, {
              method: "PATCH",
              body: JSON.stringify({ lead_state: leadState, notes }),
            });
            setBanner(`Lead ${leadState} saved.`, "ok");
            await refreshLeads();
          } catch (err) {
            setBanner(err.message, "warn");
          }
        });
      });
    } catch (err) {
      box.className = "error";
      box.textContent = err.message;
    }
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function refreshSavedSetup() {
    if (!state.token) return;
    const p = await api("/api/nova/growth-agent/profile");
    if (!p.configured) return;
    // Load persisted owner values, including the synthetic flag, so a later
    // Save does not silently relabel a demo as a real customer profile.
    $("biz-name").value = p.business_name || "";
    $("biz-web").value = p.website || "";
    $("biz-tz").value = p.timezone || "America/Chicago";
    $("biz-plan").value = p.plan_code || "starter";
    $("biz-email").value = p.contact_email || "";
    $("biz-phone").value = p.handoff_phone || "";
    $("biz-hours").value = JSON.stringify(p.operating_hours || {}, null, 2);
    $("biz-services").value = JSON.stringify(p.services || [], null, 2);
    $("biz-faqs").value = JSON.stringify(p.faqs || [], null, 2);
    $("biz-synthetic").checked = p.is_synthetic_demo === true;
  }

  async function refreshAll() {
    await Promise.all([refreshMetrics(), refreshInbox(), refreshLeads(), refreshSavedSetup()]);
  }

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await login($("login-email").value.trim(), $("login-password").value);
    } catch (err) {
      setBanner(err.message, "warn");
    }
  });
  $("sign-out").addEventListener("click", signOut);

  $("preview-setup").addEventListener("click", async () => {
    try {
      const data = await api("/api/nova/growth-agent/profile", {
        method: "POST",
        body: JSON.stringify(setupPayload({ preview_only: true })),
      });
      $("setup-preview").textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      $("setup-preview").textContent = err.message;
    }
  });
  $("save-setup").addEventListener("click", async () => {
    try {
      const data = await api("/api/nova/growth-agent/profile", {
        method: "POST",
        body: JSON.stringify(setupPayload({ activate: false })),
      });
      $("setup-preview").textContent = JSON.stringify(data, null, 2);
      setBanner("Profile saved (not necessarily activated).", "ok");
    } catch (err) {
      setBanner(err.message, "warn");
    }
  });
  $("activate-setup").addEventListener("click", async () => {
    try {
      const data = await api("/api/nova/growth-agent/profile", {
        method: "POST",
        body: JSON.stringify(setupPayload({ activate: true })),
      });
      $("setup-preview").textContent = JSON.stringify(data, null, 2);
      setBanner("Profile activated for this org (mock transports only).", "ok");
      await refreshAll();
    } catch (err) {
      setBanner(err.message, "warn");
    }
  });

  async function setAgent(paused, disabled) {
    await api("/api/nova/growth-agent/agent", {
      method: "POST",
      body: JSON.stringify({ paused, disabled }),
    });
    setBanner(`Agent state updated paused=${paused} disabled=${disabled}`, "ok");
  }
  $("pause-agent").addEventListener("click", () => setAgent(true, null).catch((e) => setBanner(e.message)));
  $("disable-agent").addEventListener("click", () => setAgent(null, true).catch((e) => setBanner(e.message)));
  $("resume-agent").addEventListener("click", () => setAgent(false, false).catch((e) => setBanner(e.message)));

  $("refresh-inbox").addEventListener("click", refreshInbox);
  $("refresh-leads").addEventListener("click", refreshLeads);
  $("lead-search").addEventListener("change", refreshLeads);

  $("create-widget").addEventListener("click", async () => {
    try {
      const data = await api("/api/nova/growth-agent/widget/installations", {
        method: "POST",
        body: JSON.stringify({ domain: $("widget-domain").value.trim() }),
      });
      $("widget-token").value = data.token || "";
      $("widget-out").textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      $("widget-out").textContent = err.message;
    }
  });

  $("widget-chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const log = $("widget-chat-log");
    const message = $("widget-message").value.trim();
    log.insertAdjacentHTML("beforeend", `<div class="bubble">${escapeHtml(message)}</div>`);
    try {
      const data = await api("/api/nova/growth-agent/widget/chat", {
        method: "POST",
        headers: { Origin: `https://${$("widget-domain").value.trim() || "demo.example.com"}` },
        body: JSON.stringify({
          token: $("widget-token").value.trim(),
          message,
          conversation_id: state.conversationId,
          visitor_name: $("widget-name").value.trim() || null,
          visitor_email: $("widget-email").value.trim() || null,
          consent_transactional: $("consent-tx").checked,
          consent_marketing: $("consent-mkt").checked,
        }),
      });
      state.conversationId = data.conversation_id;
      if (data.contact_id) $("wf-contact").value = data.contact_id;
      log.insertAdjacentHTML(
        "beforeend",
        `<div class="bubble assistant">${escapeHtml(data.reply)} <span class="tag ${data.handler}">${data.handler}</span></div>`
      );
      $("widget-message").value = "";
      await refreshAll();
    } catch (err) {
      log.insertAdjacentHTML("beforeend", `<div class="error">${escapeHtml(err.message)}</div>`);
    }
  });

  $("load-slots").addEventListener("click", async () => {
    try {
      const day = $("book-day").value || new Date().toISOString().slice(0, 10);
      const data = await api(
        `/api/nova/growth-agent/availability?service_code=${encodeURIComponent($("book-service").value)}&day=${encodeURIComponent(day)}`
      );
      if (data.slots && data.slots[0]) $("book-start").value = data.slots[0].starts_at_utc;
      $("book-out").textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      $("book-out").textContent = err.message;
    }
  });

  $("book-slot").addEventListener("click", async () => {
    try {
      const data = await api("/api/nova/growth-agent/appointments", {
        method: "POST",
        body: JSON.stringify({
          contact_id: $("wf-contact").value.trim(),
          service_code: $("book-service").value.trim(),
          starts_at_utc: $("book-start").value.trim(),
          idempotency_key: `ui-${Date.now()}`,
        }),
      });
      if (data.id) $("book-appt-id").value = data.id;
      $("book-out").textContent = JSON.stringify(data, null, 2);
      await refreshAll();
    } catch (err) {
      $("book-out").textContent = err.message;
    }
  });

  $("cancel-appt").addEventListener("click", async () => {
    try {
      const id = $("book-appt-id").value.trim();
      if (!id) throw new Error("Appointment id required");
      const data = await api(`/api/nova/growth-agent/appointments/${encodeURIComponent(id)}/cancel`, {
        method: "POST",
        body: "{}",
      });
      $("book-out").textContent = JSON.stringify(data, null, 2);
      await refreshAll();
    } catch (err) {
      $("book-out").textContent = err.message;
    }
  });

  $("reschedule-appt").addEventListener("click", async () => {
    try {
      const id = $("book-appt-id").value.trim();
      const starts = $("book-reschedule").value.trim() || $("book-start").value.trim();
      if (!id || !starts) throw new Error("Appointment id and reschedule time required");
      const data = await api(`/api/nova/growth-agent/appointments/${encodeURIComponent(id)}/reschedule`, {
        method: "POST",
        body: JSON.stringify({
          starts_at_utc: starts,
          idempotency_key: `ui-resched-${id}-${starts}`,
        }),
      });
      $("book-out").textContent = JSON.stringify(data, null, 2);
      await refreshAll();
    } catch (err) {
      $("book-out").textContent = err.message;
    }
  });

  $("recover-deliveries").addEventListener("click", async () => {
    try {
      const data = await api("/api/nova/growth-agent/workflows/recover", {
        method: "POST",
        body: "{}",
      });
      $("book-out").textContent = JSON.stringify(data, null, 2);
      await refreshMetrics();
    } catch (err) {
      $("book-out").textContent = err.message;
    }
  });

  $("opt-out-email").addEventListener("click", async () => {
    try {
      const contactId = $("wf-contact").value.trim();
      if (!contactId) throw new Error("Contact id required");
      const data = await api("/api/nova/growth-agent/consent", {
        method: "POST",
        body: JSON.stringify({
          contact_id: contactId,
          channel: "email",
          purpose: "marketing",
          status: "opted_out",
          collection_source: "owner_opt_out",
        }),
      });
      $("book-out").textContent = JSON.stringify(data, null, 2);
      setBanner("Marketing email opt-out recorded (channel-specific).", "ok");
    } catch (err) {
      $("book-out").textContent = err.message;
    }
  });

  $("preview-reminder").addEventListener("click", async () => {
    try {
      const data = await api("/api/nova/growth-agent/workflows/preview", {
        method: "POST",
        body: JSON.stringify({
          workflow_code: "appointment_reminder",
          contact_id: $("wf-contact").value.trim(),
        }),
      });
      state.workflowRunId = data.run_id;
      $("book-out").textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      $("book-out").textContent = err.message;
    }
  });

  $("exec-reminder").addEventListener("click", async () => {
    try {
      const data = await api("/api/nova/growth-agent/workflows/execute", {
        method: "POST",
        body: JSON.stringify({
          run_id: state.workflowRunId,
          dry_run: true,
          idempotency_key: `ui-exec-${state.workflowRunId}`,
        }),
      });
      $("book-out").textContent = JSON.stringify(data, null, 2);
      await refreshMetrics();
    } catch (err) {
      $("book-out").textContent = err.message;
    }
  });

  $("run-demo").addEventListener("click", async () => {
    $("demo-out").textContent = "Running synthetic demo…";
    try {
      const data = await api("/api/nova/growth-agent/demo/synthetic", {
        method: "POST",
        body: "{}",
      });
      $("demo-out").textContent = JSON.stringify(data, null, 2);
      if (data.chat && data.chat.first) {
        $("wf-contact").value = data.chat.first.contact_id || "";
      }
      if (data.reschedule && data.booking) {
        $("book-appt-id").value = data.booking.id || "";
      }
      if (data.cancel_rebook && data.cancel_rebook.rebooked_id) {
        $("book-appt-id").value = data.cancel_rebook.rebooked_id;
      }
      await refreshAll();
      setBanner("Synthetic demo complete. Records labeled Synthetic.", "ok");
    } catch (err) {
      $("demo-out").textContent = err.message;
      setBanner(err.message, "warn");
    }
  });

  $("refresh-audit").addEventListener("click", async () => {
    try {
      const data = await api("/api/nova/growth-agent/audit?limit=30");
      $("demo-out").textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      $("demo-out").textContent = err.message;
    }
  });

  $("refresh-health").addEventListener("click", async () => {
    try {
      const data = await api("/api/nova/growth-agent/health");
      $("demo-out").textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      $("demo-out").textContent = err.message;
    }
  });

  function renderDiagnosticsFlags(data) {
    const flagsEl = $("diagnostics-flags");
    if (!flagsEl) return;
    const sched = (data && data.retention_schedule) || {};
    const worker = (data && data.worker) || {};
    flagsEl.textContent = [
      `live_delivery=${data && data.live_delivery === true ? "true" : "false"}`,
      `mock_worker=${worker.mock_worker_flag ? "on" : "off"}`,
      `retention_schedule=${sched.schedule_enabled ? "on" : "off"}`,
      `retention_mode=${sched.mode || "dry_run"}`,
      `retention_delete=${sched.delete_enabled || (data && data.retention_delete_enabled) ? "on" : "off"}`,
    ].join(" · ");
  }

  $("refresh-diagnostics").addEventListener("click", async () => {
    try {
      requireSession();
      const data = await api("/api/nova/growth-agent/diagnostics");
      renderDiagnosticsFlags(data);
      $("diagnostics-out").textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      $("diagnostics-out").textContent = err.message;
      if ($("diagnostics-flags")) $("diagnostics-flags").textContent = "Sign in required for diagnostics.";
    }
  });
  $("retention-preview").addEventListener("click", async () => {
    try {
      requireSession();
      const data = await api("/api/nova/growth-agent/retention/preview", {
        method: "POST",
        body: JSON.stringify({ batch_limit: 100 }),
      });
      $("diagnostics-out").textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      $("diagnostics-out").textContent = err.message;
    }
  });
  $("retention-schedule-tick").addEventListener("click", async () => {
    try {
      requireSession();
      const data = await api("/api/nova/growth-agent/retention/schedule/tick", {
        method: "POST",
        body: JSON.stringify({ limit: 10, ensure: true }),
      });
      $("diagnostics-out").textContent = JSON.stringify(data, null, 2);
      const diag = await api("/api/nova/growth-agent/diagnostics");
      renderDiagnosticsFlags(diag);
    } catch (err) {
      $("diagnostics-out").textContent = err.message;
    }
  });
  $("worker-tick").addEventListener("click", async () => {
    try {
      requireSession();
      const data = await api("/api/nova/growth-agent/workflows/worker/tick", {
        method: "POST",
        body: JSON.stringify({ limit: 10 }),
      });
      $("diagnostics-out").textContent = JSON.stringify(data, null, 2);
      await refreshMetrics();
    } catch (err) {
      $("diagnostics-out").textContent = err.message;
    }
  });

  // Default booking day hint
  $("book-day").value = new Date(Date.now() + 2 * 86400000).toISOString().slice(0, 10);

  if (state.token) {
    sessionMeta.textContent = "Restored session token from local storage.";
    refreshAll().catch((err) => {
      setBanner(`Session restore failed: ${err.message}. Sign in again.`, "warn");
      signOut();
    });
  } else {
    setBanner(
      "Sign in required. Set NOVA_GROWTH_AGENT_ENABLED=true in local/staging. Live providers remain off.",
      "warn"
    );
  }
})();
