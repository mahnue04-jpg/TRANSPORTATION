(() => {
  const state = {
    token: localStorage.getItem("amicor_growth_token") || "",
    conversationId: null,
    workflowRunId: null,
  };

  const $ = (id) => document.getElementById(id);

  // Owner-friendly booking outcomes keep raw API results available on demand.
  // Never render API text through innerHTML or imply a Google Calendar confirmation.
  const bookingRawOutput = $("book-out");
  const bookingSummary = $("booking-result");
  const bookingTechnical = $("booking-technical");

  function localBookingTime(utc) {
    if (!utc || typeof utc !== "string") return "";
    const date = new Date(utc);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Chicago", month: "short", day: "numeric", year: "numeric",
      hour: "numeric", minute: "2-digit", timeZoneName: "short",
    }).format(date);
  }

  function bookingMessage(raw) {
    if (!raw) return { text: "", tone: "neutral" };
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      return {
        text: raw,
        tone: /error|failed|not found|must |required|cannot |unable /i.test(raw) ? "error" : "neutral",
      };
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return { text: "Booking response received. See technical details.", tone: "neutral" };
    }
    if (data.error || data.detail) {
      const detail = data.message || (typeof data.detail === "string" ? data.detail : "Check the technical details.");
      return { text: `Booking action could not be completed: ${detail}`, tone: "error" };
    }
    const time = localBookingTime(data.starts_at_utc);
    const when = time ? ` for ${time}` : "";
    const status = String(data.status || "").toLowerCase();
    let action = "";
    if (status === "confirmed") action = `Test appointment booked${when}.`;
    if (status === "rescheduled") action = `Test appointment rescheduled${when}.`;
    if (status === "cancelled") action = "Test appointment cancelled.";
    if (!action) return { text: "Booking response received. See technical details.", tone: "neutral" };
    const external = data.calendar_sync || {};
    const externalNote = external.live === false || external.status === "suppressed"
      ? " Not confirmed on Google Calendar; real notifications remain off."
      : " Check calendar status before treating this as an external confirmation.";
    return { text: action + externalNote, tone: "ok" };
  }

  function refreshBookingFeedback() {
    const raw = bookingRawOutput.textContent.trim();
    bookingSummary.hidden = !raw;
    bookingTechnical.hidden = !raw;
    if (!raw) return;
    const feedback = bookingMessage(raw);
    bookingSummary.className = `booking-result ${feedback.tone}`;
    bookingSummary.textContent = feedback.text;
    // Technical details stay available but never overwhelm the main workflow.
    bookingTechnical.open = false;
  }

  if (typeof MutationObserver === "function" && bookingRawOutput && bookingSummary && bookingTechnical) {
    new MutationObserver(refreshBookingFeedback).observe(bookingRawOutput, {
      childList: true, characterData: true, subtree: true,
    });
  }
  const banner = $("status-banner");
  const sessionMeta = $("session-meta");
  const loginForm = $("login-form");
  const loginSubmit = $("login-submit");
  const signOutButton = $("sign-out");
  let sessionVerification = 0;
  let verifiedSession = false;

  function showAuthState(mode, email = "") {
    const loggedIn = mode === "authenticated";
    const verifying = mode === "verifying";
    loginForm.querySelectorAll("input").forEach((input) => {
      input.hidden = loggedIn;
      input.disabled = loggedIn || verifying;
      const label = input.closest("label");
      if (label) label.hidden = loggedIn;
    });
    loginSubmit.hidden = loggedIn;
    loginSubmit.disabled = verifying;
    signOutButton.hidden = !loggedIn;
    verifiedSession = loggedIn;
    if (loggedIn) {
      $("login-password").value = "";
      sessionMeta.textContent = `Signed in as ${email}.`;
    }
  }

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
      const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      error.status = res.status;
      throw error;
    }
    return data;
  }

  async function verifySession(token) {
    const validation = ++sessionVerification;
    showAuthState("verifying");
    sessionMeta.textContent = "Checking your sign-in…";
    try {
      const user = await api("/api/auth/me");
      if (validation !== sessionVerification || state.token !== token) return;
      showAuthState("authenticated", user.email || "owner");
      setBanner("Signed in. Live messaging and telephone providers remain off.", "ok");
      await refreshAll();
      if (validation === sessionVerification && verifiedSession && window.NovaReceptionist?.onAuthenticated) {
        await window.NovaReceptionist.onAuthenticated();
      }
    } catch (error) {
      if (validation !== sessionVerification || state.token !== token) return;
      if (error.status === 401 || error.status === 403) {
        signOut();
        sessionMeta.textContent = "Your session expired. Please sign in again.";
      } else {
        // Transient 502/network failures are not evidence of an invalid token.
        // Preserve the saved token for a later reload, but do not mark it verified.
        state.token = "";
        showAuthState("signed-out");
        sessionMeta.textContent = "Unable to verify your sign-in. Please try again.";
        setBanner("Connection problem: owner session could not be verified.", "warn");
      }
    }
  }

  async function login(email, password) {
    showAuthState("verifying");
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      state.token = data.access_token || data.token || "";
      if (!state.token) throw new Error("No access token returned");
      localStorage.setItem("amicor_growth_token", state.token);
      await verifySession(state.token);
    } catch (error) {
      showAuthState("signed-out");
      throw error;
    }
  }

  function signOut() {
    ++sessionVerification;
    state.token = "";
    showAuthState("signed-out");
    $("login-password").value = "";
    $("login-email").value = "";
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
    if (window.NovaReceptionist && typeof window.NovaReceptionist.clearState === "function") {
      window.NovaReceptionist.clearState();
    }
  }

  function requireSession() {
    if (!state.token || !verifiedSession) {
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
            <td><button type="button" class="secondary" data-save-lead>Save</button>${l.is_synthetic_demo ? ' <button type="button" class="secondary" data-test-booking>Use for test booking</button>' : ""}</td>
          </tr>`;
        })
        .join("")}</tbody></table>`;
      // Only synthetic demo contacts may be copied into the staging booking form.
      // Never display or copy a real customer's internal identifier from this control.
      box.querySelectorAll("[data-test-booking]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const row = btn.closest("tr");
          const id = row?.dataset.leadId;
          if (!id) return;
          selectedSyntheticContactId = id;
          $("wf-contact").value = id;
          setBanner("Demo customer selected for staging booking. Return to Booking & workflows.", "ok");
        });
      });
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

  async function refreshAll() {
    await Promise.all([refreshMetrics(), refreshInbox(), refreshLeads()]);
  }

  loginForm.addEventListener("submit", async (e) => {
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

  const slotChoice = $("book-slot-choice");
  let slotRequest = 0;
  let fetchedSlotKey = "";
  let availableTimes = [];
  let selectedSyntheticContactId = "";

  function clearBookingSlots() {
    slotRequest += 1;
    fetchedSlotKey = "";
    availableTimes = [];
    $("book-start").value = "";
    slotChoice.replaceChildren(new Option("Load available times to begin", ""));
  }
  $("book-day").addEventListener("change", clearBookingSlots);
  $("book-service").addEventListener("input", clearBookingSlots);
  slotChoice.addEventListener("change", () => {
    const selected = slotChoice.value;
    $("book-start").value = availableTimes.includes(selected) ? selected : "";
  });
  $("prepare-synthetic-contact").addEventListener("click", async () => {
    try {
      requireSession();
      const data = await api("/api/nova/growth-agent/staging/booking-contact", {
        method: "POST",
        body: "{}",
      });
      if (!data.is_synthetic_demo || !data.staging_only || !data.contact_id) {
        throw new Error("Synthetic test customer was not verified.");
      }
      selectedSyntheticContactId = data.contact_id;
      $("wf-contact").value = data.contact_id;
      $("book-out").textContent = "Synthetic test customer prepared and selected. Load available times and choose a slot. No appointment has been created.";
      await refreshLeads();
    } catch (err) {
      $("book-out").textContent = err.message;
    }
  });
  $("prepare-staging-service").addEventListener("click", async () => {
    try {
      requireSession();
      clearBookingSlots();
      const code = $("book-service").value.trim();
      if (!code) throw new Error("Enter a service code from the saved business setup.");
      const response = await api("/api/nova/growth-agent/staging/booking-service", {
        method: "POST",
        body: JSON.stringify({ service_code: code }),
      });
      $("book-out").textContent = response.created
        ? "Test service prepared. Now click Load available times. Live calling and Google Calendar remain off."
        : "Test service is ready. Click Load available times. Live calling and Google Calendar remain off.";
    } catch (err) {
      $("book-out").textContent = err.message;
    }
  });

  $("load-slots").addEventListener("click", async () => {
    clearBookingSlots();
    const request = slotRequest;
    try {
      requireSession();
      const day = $("book-day").value;
      const service = $("book-service").value.trim();
      if (!day || !service) throw new Error("Choose an appointment day and service first.");
      const key = `${service}|${day}`;
      const data = await api(
        `/api/nova/growth-agent/availability?service_code=${encodeURIComponent(service)}&day=${encodeURIComponent(day)}`
      );
      if (request !== slotRequest) return;
      const count = window.NovaBookingSlots.populate(slotChoice, data);
      availableTimes = window.NovaBookingSlots.availableSlots(data);
      fetchedSlotKey = key;
      $("book-out").textContent = count
        ? `Choose one of the ${count} available times listed above. This is a staging booking, not a Google Calendar confirmation.`
        : "No available times were returned for this service and date.";
    } catch (err) {
      if (request !== slotRequest) return;
      $("book-out").textContent = err.message;
    }
  });

  $("book-slot").addEventListener("click", async () => {
    try {
      requireSession();
      const contactId = $("wf-contact").value.trim();
      const service = $("book-service").value.trim();
      const key = `${service}|${$("book-day").value}`;
      const selected = slotChoice.value;
      if (!contactId) throw new Error("Select an existing customer ID from the CRM first.");
      if (!selected || !availableTimes.includes(selected) || key !== fetchedSlotKey ||
          $("book-start").value !== selected) {
        throw new Error("Load available times and choose one before creating a staging appointment.");
      }
      const data = await api("/api/nova/growth-agent/appointments", {
        method: "POST",
        body: JSON.stringify({
          contact_id: contactId,
          service_code: service,
          starts_at_utc: selected,
          idempotency_key: `ui-${Date.now()}`,
          is_synthetic_demo: Boolean(selectedSyntheticContactId) && contactId === selectedSyntheticContactId,
        }),
      });
      if (data.id) $("book-appt-id").value = data.id;
      $("book-out").textContent = JSON.stringify(data, null, 2);
      clearBookingSlots();
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

  window.NovaGrowthSession = { isVerified: () => verifiedSession };
  if (state.token) {
    verifySession(state.token);
  } else {
    showAuthState("signed-out");
    setBanner("Sign in required. Live messaging and telephone providers remain off.", "warn");
  }
})();
