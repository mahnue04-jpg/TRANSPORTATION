(() => {
  const cache = {
    status: null,
    calendar: null,
    syncErrors: null,
    notifications: null,
    handoffs: null,
    voiceResult: null,
    faqSummary: null,
    readiness: null,
    tokenSnapshot: null,
  };

  let sessionGeneration = 0;

  const OAUTH_PENDING_KEY = "ga_calendar_oauth_pending";
  const TOKEN_KEY = "amicor_growth_token";
  const DEFAULT_CALLED = "+15555550100";
  const DEFAULT_CALLER = "+15555550101";

  const $ = (id) => document.getElementById(id);

  const SENSITIVE_KEY =
    /^(access_token|refresh_token|token|oauth_token|id_token|credentials|client_secret)$/i;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function redactForDisplay(value) {
    if (value == null) return value;
    if (Array.isArray(value)) return value.map(redactForDisplay);
    if (typeof value === "object") {
      const out = {};
      for (const [key, val] of Object.entries(value)) {
        if (SENSITIVE_KEY.test(key)) {
          out[key] = "[redacted]";
        } else {
          out[key] = redactForDisplay(val);
        }
      }
      return out;
    }
    return value;
  }

  function readToken() {
    return localStorage.getItem(TOKEN_KEY) || "";
  }

  function authHeaders() {
    const headers = { "Content-Type": "application/json" };
    const token = readToken();
    if (token) headers.Authorization = `Bearer ${token}`;
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
    return redactForDisplay(data);
  }

  function isCalendarConnected(calendar) {
    if (!calendar) return false;
    if (typeof calendar.connected === "boolean") return calendar.connected === true;
    const status = String(calendar.status || "").trim().toLowerCase();
    return status === "connected";
  }

  function normalizeCalendar(calendar) {
    const base = calendar && typeof calendar === "object" ? { ...calendar } : {};
    base.connected = isCalendarConnected(calendar);
    return base;
  }

  function readinessTone(kind) {
    if (kind === "ok") return "recv-status-ok";
    if (kind === "warn") return "recv-status-warn";
    return "recv-status-muted";
  }

  function normalizeConnectionState(raw) {
    const value = String(raw || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "_");
    if (!value || value === "unknown" || value === "unverified") return "unverified";
    if (value === "not_connected" || value === "disconnected") return "disconnected";
    if (
      value === "missing_config" ||
      value === "missing_configuration" ||
      value === "oauth_not_configured" ||
      value === "not_configured"
    ) {
      return "missing_config";
    }
    if (value === "needs_reconnect" || value === "expired") return "needs_reconnect";
    if (value === "revoked") return "revoked";
    if (value === "connected") return "connected";
    if (value === "error" || value === "failed") return "needs_reconnect";
    return value;
  }

  function connectionStateLabel(state) {
    switch (normalizeConnectionState(state)) {
      case "connected":
        return "Connected";
      case "disconnected":
        return "Not connected";
      case "missing_config":
        return "Missing configuration";
      case "needs_reconnect":
        return "Needs reconnect";
      case "revoked":
        return "Revoked";
      default:
        return "Unverified";
    }
  }

  function connectionStateTone(state) {
    const normalized = normalizeConnectionState(state);
    if (normalized === "connected") return "ok";
    if (normalized === "unverified") return "muted";
    return "warn";
  }

  function normalizeCredentialHealth(raw) {
    let value = raw;
    if (raw && typeof raw === "object") {
      value = raw.state || raw.credential_health || raw.status || "";
      if (!value && raw.has_refresh_credential === false) value = "missing_refresh";
      if (!value && raw.refresh_needed === true && raw.has_refresh_credential) value = "expired";
    }
    value = String(value || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "_");
    if (!value) return "unverified";
    if (value === "healthy" || value === "ok") return "healthy";
    if (
      value === "expired" ||
      value === "credentials_expired" ||
      value === "needs_reconnect"
    ) {
      return "expired";
    }
    if (
      value === "missing_refresh" ||
      value === "refresh_token_missing" ||
      value === "missing_refresh_token" ||
      value === "missing_connection"
    ) {
      return "missing_refresh";
    }
    return "unverified";
  }

  function credentialHealthLabel(health) {
    switch (normalizeCredentialHealth(health)) {
      case "healthy":
        return "Healthy";
      case "expired":
        return "Expired";
      case "missing_refresh":
        return "Missing refresh";
      default:
        return "Unverified";
    }
  }

  function normalizeSyncQueue(queue) {
    const src = queue && typeof queue === "object" ? queue : {};
    const counts = src.counts && typeof src.counts === "object" ? src.counts : {};
    const pendingFromCounts =
      Number(counts.pending || 0) + Number(counts.retrying || 0) + Number(counts.running || 0);
    const pending =
      src.pending_or_running != null
        ? Number(src.pending_or_running) || 0
        : src.pending != null
          ? Number(src.pending) || 0
          : pendingFromCounts;
    const failed = src.failed != null ? Number(src.failed) || 0 : Number(counts.failed) || 0;
    const running = src.running != null ? Number(src.running) || 0 : Number(counts.running) || 0;
    const recoverable = Array.isArray(src.recoverable_errors)
      ? src.recoverable_errors
      : Array.isArray(src.errors)
        ? src.errors
        : [];
    const empty =
      typeof src.empty === "boolean"
        ? src.empty
        : String(src.state || "").toLowerCase() === "empty" ||
          (pending === 0 && failed === 0 && running === 0);
    return {
      pending,
      failed,
      running,
      recoverable_errors: recoverable,
      empty,
      label: src.label || null,
      state: src.state || null,
    };
  }

  function normalizeTwilio(twilio) {
    const src = twilio && typeof twilio === "object" ? twilio : {};
    const webhook = src.webhook && typeof src.webhook === "object" ? src.webhook : {};
    const mappingRaw = String(
      src.mapping_state || src.mapping || src.number_mapping || ""
    )
      .trim()
      .toLowerCase();
    let mapping = "unverified";
    if (mappingRaw === "mapped") mapping = "mapped";
    else if (mappingRaw === "unmapped") mapping = "unmapped";
    else if (mappingRaw === "inactive_or_kill_switch") mapping = "unmapped";

    const modeRaw = String(src.mode || src.voice_mode || "").trim().toLowerCase();
    let mode = "unverified";
    if (
      modeRaw === "simulator" ||
      modeRaw === "simulated" ||
      src.simulated === true ||
      webhook.simulator_enabled === true ||
      webhook.live_voice === false ||
      /simulated/i.test(String(webhook.label || ""))
    ) {
      mode = "simulator";
    } else if (
      modeRaw === "live_off" ||
      modeRaw === "live-off" ||
      modeRaw === "off" ||
      src.live === false
    ) {
      mode = "live_off";
    }
    const webhookReady =
      typeof webhook.ready === "boolean"
        ? webhook.ready
        : typeof src.webhook_ready === "boolean"
          ? src.webhook_ready
          : typeof src.webhook_readiness === "boolean"
            ? src.webhook_readiness
            : null;
    return {
      mapping,
      webhook_ready: webhookReady,
      mode,
      simulated: mode === "simulator" || src.simulated === true || webhook.live_voice === false,
      label: src.label || webhook.label || null,
    };
  }

  function normalizeNotificationsReadiness(notifications) {
    const src = notifications && typeof notifications === "object" ? notifications : {};
    const configuration =
      src.configuration && typeof src.configuration === "object" ? src.configuration : {};
    const counts = src.counts && typeof src.counts === "object" ? src.counts : {};
    const honesty = src.honesty && typeof src.honesty === "object" ? src.honesty : {};
    let configured = null;
    if (typeof src.configured === "boolean") configured = src.configured;
    else if (src.worker_enabled === true || configuration.adapter) configured = true;
    else if (src.worker_enabled === false && !configuration.adapter) configured = false;
    else if (src.config_state) {
      const cs = String(src.config_state).toLowerCase();
      configured = cs !== "missing" && cs !== "missing_config";
    }

    let delivery = String(
      src.delivery_state || src.recent_status || src.status || src.state || ""
    ).trim();
    if (!delivery || delivery === "active" || delivery === "empty") {
      if (counts.provider_accepted) delivery = "provider_accepted";
      else if (counts.failed) delivery = "failed";
      else if (counts.queued) delivery = "queued";
      else if (String(src.state || "").toLowerCase() === "empty") delivery = "empty";
      else delivery = delivery || "Unverified";
    }
    const honestyNote =
      src.honesty_note ||
      (honesty.provider_accepted_is_not_inbox_receipt
        ? "provider_accepted is not inbox receipt — delivery acknowledged by provider only"
        : "provider_accepted is not inbox receipt — delivery acknowledged by provider only");
    return {
      configured,
      delivery_state: delivery || "Unverified",
      honesty_note: honestyNote,
      label: src.label || null,
      counts,
    };
  }

  function normalizeReadiness(payload) {
    if (!payload || typeof payload !== "object") return null;
    const embedded = payload.readiness && typeof payload.readiness === "object";
    const root = embedded ? payload.readiness : payload;
    // Dedicated readiness responses include sync_queue / voice; bare calendar status does not.
    const looksLikeReadiness =
      root.sync_queue != null ||
      root.voice != null ||
      root.twilio != null ||
      (root.calendar && root.calendar.credential_health != null) ||
      root.pilot_live_ready != null;
    if (!embedded && !looksLikeReadiness && payload.calendar && !payload.sync_queue) {
      // Avoid treating plain /receptionist/status as readiness.
      return null;
    }
    const calendarSrc = root.calendar && typeof root.calendar === "object" ? root.calendar : {};
    const configuration =
      calendarSrc.configuration && typeof calendarSrc.configuration === "object"
        ? calendarSrc.configuration
        : {};
    let connectionState =
      calendarSrc.connection_state ||
      configuration.state ||
      calendarSrc.state ||
      calendarSrc.status ||
      (typeof calendarSrc.connected === "boolean"
        ? calendarSrc.connected
          ? "connected"
          : "disconnected"
        : "");
    if (
      calendarSrc.configured === false ||
      calendarSrc.config_missing === true ||
      String(configuration.state || "").toLowerCase() === "missing_configuration"
    ) {
      connectionState = "missing_config";
    }
    const credentialHealth =
      calendarSrc.credential_health ||
      calendarSrc.credentials_health ||
      calendarSrc.credential_state ||
      "";
    const syncQueue = normalizeSyncQueue(root.sync_queue || root.syncQueue || root.queue);
    const notifications = normalizeNotificationsReadiness(
      root.notifications && !Array.isArray(root.notifications)
        ? root.notifications
        : root.notification || root.owner_notifications || {}
    );
    const twilio = normalizeTwilio(root.twilio || root.voice || root.telephony);
    const honesty = root.honesty && typeof root.honesty === "object" ? root.honesty : {};
    return {
      calendar: {
        connection_state: normalizeConnectionState(connectionState),
        configured:
          typeof calendarSrc.configured === "boolean"
            ? calendarSrc.configured
            : normalizeConnectionState(connectionState) !== "missing_config",
        calendar_id:
          calendarSrc.selected_calendar_id ||
          calendarSrc.calendar_id ||
          null,
        calendar_summary:
          calendarSrc.selected_calendar_summary ||
          calendarSrc.calendar_summary ||
          calendarSrc.summary ||
          null,
        credential_health: normalizeCredentialHealth(credentialHealth),
        configuration_label: configuration.label || null,
      },
      sync_queue: syncQueue,
      notifications,
      twilio,
      honesty,
      source: embedded ? "status_embed" : "readiness",
    };
  }

  function extractReadinessFromStatus(statusPayload) {
    if (!statusPayload || typeof statusPayload !== "object") return null;
    if (statusPayload.readiness && typeof statusPayload.readiness === "object") {
      return normalizeReadiness(statusPayload.readiness);
    }
    return null;
  }

  function buildVoiceSimulatorPayload(intent, utterance, calledNumber, callerNumber) {
    return {
      called_number: (calledNumber || DEFAULT_CALLED).trim(),
      caller_number: (callerNumber || DEFAULT_CALLER).trim(),
      intent: (intent || "general").trim(),
      utterance: (utterance || "What are your hours?").trim(),
      simulated: true,
    };
  }

  function readOAuthReturnParams() {
    const params = new URLSearchParams(window.location.search);
    const oauthError = params.get("oauth_error");
    if (oauthError) {
      return { error: oauthError };
    }
    const explicitState = params.get("calendar_oauth_state");
    const explicitCode = params.get("calendar_oauth_code");
    if (explicitState && explicitCode) {
      return { state: explicitState, code: explicitCode };
    }
    // Server GET callback redirects here with calendar_oauth=1&state&code
    const state = params.get("state");
    const code = params.get("code");
    const fromCallback = params.get("calendar_oauth") === "1";
    if (state && code && (fromCallback || sessionStorage.getItem(OAUTH_PENDING_KEY) === "1")) {
      return { state, code };
    }
    return null;
  }

  function stripOAuthQueryFromUrl() {
    const url = new URL(window.location.href);
    [
      "calendar_oauth_state",
      "calendar_oauth_code",
      "calendar_oauth",
      "oauth_error",
      "state",
      "code",
    ].forEach((key) => {
      url.searchParams.delete(key);
    });
    const search = url.searchParams.toString();
    const next = url.pathname + (search ? `?${search}` : "") + url.hash;
    history.replaceState({}, document.title, next);
  }

  function abortIfStale(gen) {
    return gen !== sessionGeneration;
  }

  function onTokenChangedFromSnapshot() {
    const token = readToken();
    if (cache.tokenSnapshot !== null && token !== cache.tokenSnapshot) {
      clearState();
      return true;
    }
    return false;
  }

  function setupFaqSummaryFromDom() {
    const hours = $("biz-hours");
    const faqs = $("biz-faqs");
    const name = $("biz-name");
    if (!hours && !faqs) return null;
    let faqCount = 0;
    try {
      const parsed = JSON.parse((faqs && faqs.value.trim()) || "[]");
      faqCount = Array.isArray(parsed) ? parsed.length : 0;
    } catch {
      faqCount = 0;
    }
    let hoursPreview = "";
    try {
      hoursPreview = JSON.stringify(JSON.parse((hours && hours.value.trim()) || "{}"));
    } catch {
      hoursPreview = (hours && hours.value.trim()) || "{}";
    }
    return {
      business_name: name ? name.value.trim() || "—" : "—",
      faq_count: faqCount,
      hours_preview: hoursPreview.slice(0, 120),
    };
  }

  function renderCalendarSection(calendar) {
    const connected = isCalendarConnected(calendar);
    const statusLabel = connected
      ? escapeHtml(calendar.status === "connected" ? "Connected" : calendar.status || "Connected")
      : "Not connected";
    const statusClass = connected ? "ok" : "warn";
    const calendarId = connected
      ? escapeHtml(calendar.calendar_id || calendar.selected_calendar_id || "—")
      : "—";
    const summary = connected
      ? escapeHtml(calendar.summary || calendar.calendar_summary || "—")
      : "—";
    const syncState = calendar && calendar.sync_state ? escapeHtml(calendar.sync_state) : "—";
    return `
      <article class="recv-card" data-recv-calendar>
        <h3>Calendar</h3>
        <p class="recv-status recv-status-${statusClass}">${statusLabel}</p>
        <dl class="recv-dl">
          <div><dt>Calendar id</dt><dd>${calendarId}</dd></div>
          <div><dt>Summary</dt><dd>${summary}</dd></div>
          <div><dt>Sync state</dt><dd>${syncState}</dd></div>
        </dl>
        <div class="actions">
          <button type="button" id="recv-connect-calendar" class="secondary">Connect Google Calendar</button>
          <button type="button" id="recv-disconnect-calendar" class="secondary">Disconnect</button>
        </div>
        <p class="hint">External calendar sync is pending until the provider acknowledges. Mock bookings are not externally confirmed.</p>
      </article>`;
  }

  function renderSyncErrorsSection(errors) {
    const rows = Array.isArray(errors) ? errors : errors && errors.items ? errors.items : [];
    if (!rows.length) {
      return `
        <article class="recv-card" data-recv-sync-errors>
          <h3>Sync errors</h3>
          <p class="empty">No pending or failed sync errors.</p>
        </article>`;
    }
    const body = rows
      .map(
        (row) => `<tr>
          <td><span class="tag ${escapeHtml(row.state || row.status || "pending")}">${escapeHtml(
          row.state || row.status || "pending"
        )}</span></td>
          <td>${escapeHtml(row.operation || row.kind || "—")}</td>
          <td>${escapeHtml(row.message || row.detail || "—")}</td>
          <td>${escapeHtml(row.updated_at || row.created_at || "")}</td>
        </tr>`
      )
      .join("");
    return `
      <article class="recv-card" data-recv-sync-errors>
        <h3>Sync errors</h3>
        <div class="recv-table-wrap">
          <table class="table">
            <thead><tr><th>State</th><th>Operation</th><th>Detail</th><th>Updated</th></tr></thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      </article>`;
  }

  function renderNotificationsSection(notifications) {
    const rows = Array.isArray(notifications)
      ? notifications
      : notifications && notifications.items
        ? notifications.items
        : [];
    if (!rows.length) {
      return `
        <article class="recv-card" data-recv-notifications>
          <h3>Notifications</h3>
          <p class="empty">No notification deliveries logged.</p>
        </article>`;
    }
    const body = rows
      .map(
        (n) => `<tr>
          <td>${escapeHtml(n.channel || "—")}</td>
          <td><span class="tag">${escapeHtml(n.status || "unknown")}</span></td>
          <td>${escapeHtml(n.summary || n.subject || "—")}</td>
        </tr>`
      )
      .join("");
    return `
      <article class="recv-card" data-recv-notifications>
        <h3>Notifications</h3>
        <div class="recv-table-wrap">
          <table class="table">
            <thead><tr><th>Channel</th><th>Status</th><th>Summary</th></tr></thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      </article>`;
  }

  function renderHandoffsSection(handoffs) {
    const rows = Array.isArray(handoffs) ? handoffs : handoffs && handoffs.items ? handoffs.items : [];
    if (!rows.length) {
      return `
        <article class="recv-card" data-recv-handoffs>
          <h3>Handoff queue</h3>
          <p class="empty">No handoffs waiting for owner acknowledgement.</p>
        </article>`;
    }
    const body = rows
      .map(
        (h) => `<tr>
          <td>${escapeHtml(h.reason || h.subject || h.id)}</td>
          <td>${escapeHtml(h.caller_summary || h.from || "—")}</td>
          <td><span class="tag human">${escapeHtml(h.status || "open")}</span></td>
          <td>
            <button type="button" class="secondary recv-ack" data-handoff-id="${escapeHtml(h.id)}">Acknowledge</button>
          </td>
        </tr>`
      )
      .join("");
    return `
      <article class="recv-card" data-recv-handoffs>
        <h3>Handoff queue</h3>
        <div class="recv-table-wrap">
          <table class="table">
            <thead><tr><th>Reason</th><th>Source</th><th>Status</th><th></th></tr></thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      </article>`;
  }

  function renderAgentStatusSection(status) {
    const paused = status && status.paused === true;
    const disabled = status && status.disabled === true;
    const label = status && status.agent_label ? status.agent_label : "receptionist";
    const stateText = disabled
      ? "Disabled (kill switch)"
      : paused
        ? "Paused"
        : status && status.active === false
          ? "Inactive"
          : "Active (pilot)";
    return `
      <article class="recv-card" data-recv-agent>
        <h3>Agent controls</h3>
        <p class="recv-status ${disabled || paused ? "recv-status-warn" : "recv-status-ok"}">${escapeHtml(stateText)}</p>
        <p class="hint">Label: ${escapeHtml(label)}. Use <strong>Pause</strong>, <strong>Disable</strong>, or <strong>Resume</strong> in the Setup wizard panel.</p>
      </article>`;
  }

  function renderFaqSection(summary) {
    const s = summary || { business_name: "—", faq_count: 0, hours_preview: "{}" };
    return `
      <article class="recv-card" data-recv-faq>
        <h3>Business FAQs &amp; hours</h3>
        <p class="hint">${escapeHtml(s.business_name)} — ${s.faq_count} FAQ entr${s.faq_count === 1 ? "y" : "ies"} in setup.</p>
        <p class="hint recv-mono">Hours preview: ${escapeHtml(s.hours_preview)}</p>
        <p class="hint"><a href="#setup-wizard" class="recv-link">Edit FAQs and hours in Setup wizard</a></p>
      </article>`;
  }

  function renderVoiceSimulatorSection(voiceResult) {
    const output = voiceResult
      ? `<pre class="hint recv-pre" aria-live="polite">${escapeHtml(JSON.stringify(voiceResult, null, 2))}</pre>`
      : `<p class="hint" id="recv-voice-out">Run a simulated call flow — results stay on-device until APIs respond.</p>`;
    return `
      <article class="recv-card recv-voice" data-recv-voice>
        <div class="recv-sim-banner" role="note">SIMULATED — not a live phone call</div>
        <h3>Voice simulator</h3>
        <p class="hint">Dry-run receptionist voice handling. No PSTN, no customer outreach.</p>
        <label>Called number (E.164)<input id="recv-voice-called" type="text" value="${DEFAULT_CALLED}" autocomplete="off" /></label>
        <label>Caller number (E.164)<input id="recv-voice-caller" type="text" value="${DEFAULT_CALLER}" autocomplete="off" /></label>
        <label>Caller intent<input id="recv-voice-intent" type="text" placeholder="Book a consultation" /></label>
        <label>Utterance<input id="recv-voice-utterance" type="text" placeholder="What are your hours tomorrow?" /></label>
        <div class="actions">
          <button type="button" id="recv-run-voice">Run simulated call</button>
        </div>
        ${output}
      </article>`;
  }

  function renderReadinessRecoverableErrors(errors) {
    const rows = Array.isArray(errors) ? errors : [];
    if (!rows.length) return "";
    const items = rows
      .slice(0, 5)
      .map((row) => {
        const code = escapeHtml(row.code || row.error_code || row.last_error_code || "");
        const message = escapeHtml(row.message || row.detail || row.operation || "recoverable");
        return `<li>${code ? `${code}: ` : ""}${message}</li>`;
      })
      .join("");
    return `<ul class="recv-readiness-errors hint">${items}</ul>`;
  }

  function renderReadinessSection(readiness) {
    if (!readiness) {
      return `
      <article class="recv-card recv-readiness" data-recv-readiness>
        <div class="recv-sim-banner" role="note">Unverified</div>
        <h3>Readiness</h3>
        <p class="recv-status ${readinessTone("muted")}">Unverified</p>
        <p class="hint">Owner readiness payload not available yet. Missing configuration is not a failed connection.</p>
      </article>`;
    }

    const calendar = readiness.calendar || {};
    const queue = readiness.sync_queue || normalizeSyncQueue({});
    const notifications = readiness.notifications || normalizeNotificationsReadiness({});
    const twilio = readiness.twilio || normalizeTwilio({});
    const connState = normalizeConnectionState(calendar.connection_state);
    const connLabel = connectionStateLabel(connState);
    const credLabel = credentialHealthLabel(calendar.credential_health);
    const credTone =
      normalizeCredentialHealth(calendar.credential_health) === "healthy"
        ? "ok"
        : normalizeCredentialHealth(calendar.credential_health) === "unverified"
          ? "muted"
          : "warn";
    const calendarId = escapeHtml(calendar.calendar_id || "—");
    const calendarSummary = escapeHtml(calendar.calendar_summary || "—");
    const configLabel =
      calendar.configured === false || connState === "missing_config"
        ? "Missing configuration"
        : calendar.configured === true
          ? "Configured"
          : "Unverified";
    const queueTone = queue.failed > 0 ? "warn" : "ok";
    const queueLabel =
      queue.label ||
      (queue.empty
        ? "Empty queue (not a failure)"
        : queue.failed > 0
          ? "Queue has failures"
          : "Queue active");
    const notifyConfigured =
      notifications.configured === true
        ? "Configured"
        : notifications.configured === false
          ? "Missing configuration"
          : "Unverified";
    const deliveryRaw = String(notifications.delivery_state || "Unverified");
    const deliveryLabel =
      deliveryRaw.toLowerCase() === "provider_accepted"
        ? "provider_accepted (not inbox receipt)"
        : deliveryRaw.toLowerCase() === "empty"
          ? "Empty queue (not a failure)"
          : deliveryRaw || "Unverified";
    const mappingLabel =
      twilio.label ||
      (twilio.mapping === "mapped"
        ? "Mapped"
        : twilio.mapping === "unmapped"
          ? "Unmapped"
          : "Unverified");
    const webhookLabel =
      twilio.webhook_ready === true
        ? "Webhook ready"
        : twilio.webhook_ready === false
          ? "Webhook not ready"
          : "Unverified";
    const twilioMode =
      twilio.mode === "simulator"
        ? "SIMULATED"
        : twilio.mode === "live_off"
          ? "Live-off"
          : "Unverified";
    const showSimBanner = twilio.simulated || twilio.mode === "simulator";
    const calendarConfigDetail = calendar.configuration_label
      ? `<p class="hint">${escapeHtml(calendar.configuration_label)}</p>`
      : "";

    return `
      <article class="recv-card recv-readiness" data-recv-readiness>
        ${
          showSimBanner
            ? `<div class="recv-sim-banner" role="note">SIMULATED — voice/live paths not independently verified</div>`
            : `<div class="recv-unverified-banner" role="note">Unverified — owner readiness snapshot</div>`
        }
        <h3>Readiness</h3>
        <p class="hint">Distinguishes missing configuration, failed connection, and an empty sync queue.</p>
        <div class="recv-readiness-grid">
          <section class="recv-readiness-block" data-recv-readiness-calendar>
            <h4>Calendar</h4>
            <p class="recv-status ${readinessTone(connectionStateTone(connState))}">${escapeHtml(connLabel)}</p>
            <dl class="recv-dl">
              <div><dt>Configuration</dt><dd>${escapeHtml(configLabel)}</dd></div>
              <div><dt>Selected calendar</dt><dd class="recv-mono">${calendarId}</dd></div>
              <div><dt>Summary</dt><dd>${calendarSummary}</dd></div>
              <div><dt>Credential health</dt><dd class="recv-status ${readinessTone(credTone)}">${escapeHtml(
                credLabel
              )}</dd></div>
            </dl>
            ${calendarConfigDetail}
          </section>
          <section class="recv-readiness-block" data-recv-readiness-sync>
            <h4>Sync queue</h4>
            <p class="recv-status ${readinessTone(queueTone)}">${escapeHtml(queueLabel)}</p>
            <dl class="recv-dl">
              <div><dt>Pending</dt><dd>${queue.pending}</dd></div>
              <div><dt>Running</dt><dd>${queue.running}</dd></div>
              <div><dt>Failed</dt><dd>${queue.failed}</dd></div>
            </dl>
            ${renderReadinessRecoverableErrors(queue.recoverable_errors)}
          </section>
          <section class="recv-readiness-block" data-recv-readiness-notifications>
            <h4>Notifications</h4>
            <p class="recv-status ${readinessTone(
              notifications.configured === false ? "warn" : notifications.configured ? "ok" : "muted"
            )}">${escapeHtml(notifyConfigured)}</p>
            <dl class="recv-dl">
              <div><dt>Delivery state</dt><dd>${escapeHtml(deliveryLabel)}</dd></div>
            </dl>
            <p class="hint">${escapeHtml(notifications.honesty_note)}</p>
          </section>
          <section class="recv-readiness-block" data-recv-readiness-twilio>
            <h4>Twilio / webhook</h4>
            <p class="recv-status ${readinessTone(
              twilio.mapping === "mapped" ? "ok" : twilio.mapping === "unmapped" ? "warn" : "muted"
            )}">${escapeHtml(mappingLabel)}</p>
            <dl class="recv-dl">
              <div><dt>Webhook</dt><dd>${escapeHtml(webhookLabel)}</dd></div>
              <div><dt>Mode</dt><dd><span class="recv-label-sim">${escapeHtml(twilioMode)}</span></dd></div>
            </dl>
          </section>
        </div>
      </article>`;
  }

  function renderReceptionistPanel(data) {
    const status = data && data.status ? data.status : {};
    const calendar = normalizeCalendar(data && data.calendar ? data.calendar : { connected: false });
    return `
      <div class="recv-grid">
        ${renderReadinessSection(data && data.readiness)}
        ${renderFaqSection(data && data.faqSummary)}
        ${renderAgentStatusSection(status)}
        ${renderCalendarSection(calendar)}
        ${renderSyncErrorsSection(data && data.syncErrors)}
        ${renderNotificationsSection(data && data.notifications)}
        ${renderHandoffsSection(data && data.handoffs)}
        ${renderVoiceSimulatorSection(data && data.voiceResult)}
      </div>`;
  }

  function bindPanelActions(root) {
    if (!root) return;
    const refreshBtn = $("recv-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", () => refresh().catch(showRecvError));

    const connect = root.querySelector("#recv-connect-calendar");
    if (connect) {
      connect.addEventListener("click", async () => {
        const gen = sessionGeneration;
        try {
          requireSession();
          const data = await api("/api/nova/growth-agent/calendar/oauth/start", {
            method: "POST",
            body: "{}",
          });
          if (abortIfStale(gen)) return;
          if (data && data.authorization_url) {
            try {
              sessionStorage.setItem(OAUTH_PENDING_KEY, "1");
            } catch {
              /* sessionStorage unavailable */
            }
            window.location.assign(data.authorization_url);
          } else {
            showRecvError("OAuth start did not return an authorization URL (pilot API may be offline).");
          }
        } catch (err) {
          if (!abortIfStale(gen)) showRecvError(err.message);
        }
      });
    }

    const disconnect = root.querySelector("#recv-disconnect-calendar");
    if (disconnect) {
      disconnect.addEventListener("click", async () => {
        const gen = sessionGeneration;
        try {
          requireSession();
          await api("/api/nova/growth-agent/calendar/disconnect", { method: "POST", body: "{}" });
          if (abortIfStale(gen)) return;
          await refresh();
        } catch (err) {
          if (!abortIfStale(gen)) showRecvError(err.message);
        }
      });
    }

    const runVoice = root.querySelector("#recv-run-voice");
    if (runVoice) {
      runVoice.addEventListener("click", async () => {
        const gen = sessionGeneration;
        try {
          requireSession();
          const intent = ($("recv-voice-intent") && $("recv-voice-intent").value.trim()) || "general";
          const utterance =
            ($("recv-voice-utterance") && $("recv-voice-utterance").value.trim()) ||
            "What are your hours?";
          const called =
            ($("recv-voice-called") && $("recv-voice-called").value.trim()) || DEFAULT_CALLED;
          const caller =
            ($("recv-voice-caller") && $("recv-voice-caller").value.trim()) || DEFAULT_CALLER;
          const body = buildVoiceSimulatorPayload(intent, utterance, called, caller);
          const data = await api("/api/nova/growth-agent/voice/simulator/run", {
            method: "POST",
            body: JSON.stringify(body),
          });
          if (abortIfStale(gen)) return;
          cache.voiceResult = data;
          paintPanel();
        } catch (err) {
          if (abortIfStale(gen)) return;
          cache.voiceResult = { simulated: true, error: err.message };
          paintPanel();
        }
      });
    }

    root.querySelectorAll(".recv-ack").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const gen = sessionGeneration;
        const id = btn.getAttribute("data-handoff-id");
        if (!id) return;
        try {
          requireSession();
          await api(`/api/nova/growth-agent/handoffs/${encodeURIComponent(id)}/acknowledge`, {
            method: "POST",
            body: "{}",
          });
          if (abortIfStale(gen)) return;
          await refresh();
        } catch (err) {
          if (!abortIfStale(gen)) showRecvError(err.message);
        }
      });
    });
  }

  function requireSession() {
    if (!readToken()) throw new Error("Sign in required before using receptionist controls.");
  }

  function showRecvError(message) {
    const el = $("receptionist-status");
    if (el) {
      el.className = "error";
      el.textContent = message;
    }
  }

  function clearRecvStatus() {
    const el = $("receptionist-status");
    if (el) {
      el.className = "hint";
      el.textContent = "";
    }
  }

  function paintPanel() {
    const root = $("receptionist-root");
    if (!root) return;
    root.innerHTML = renderReceptionistPanel({
      status: cache.status,
      calendar: cache.calendar || { connected: false },
      syncErrors: cache.syncErrors,
      notifications: cache.notifications,
      handoffs: cache.handoffs,
      voiceResult: cache.voiceResult,
      faqSummary: cache.faqSummary,
      readiness: cache.readiness,
    });
    bindPanelActions(root);
  }

  function clearState() {
    sessionGeneration += 1;
    cache.status = null;
    cache.calendar = null;
    cache.syncErrors = null;
    cache.notifications = null;
    cache.handoffs = null;
    cache.voiceResult = null;
    cache.faqSummary = null;
    cache.readiness = null;
    cache.tokenSnapshot = null;
    const root = $("receptionist-root");
    if (root) {
      root.innerHTML = `<div class="hint">Signed out — receptionist state cleared.</div>`;
    }
    clearRecvStatus();
  }

  async function completeCalendarOAuthIfNeeded() {
    const gen = sessionGeneration;
    const oauth = readOAuthReturnParams();
    if (!oauth) return false;
    if (oauth.error) {
      if (!abortIfStale(gen)) {
        showRecvError(`Calendar connection was not completed (${oauth.error}).`);
      }
      stripOAuthQueryFromUrl();
      try {
        sessionStorage.removeItem(OAUTH_PENDING_KEY);
      } catch {
        /* ignore */
      }
      return false;
    }
    if (!readToken()) return false;
    try {
      requireSession();
      await api("/api/nova/growth-agent/calendar/oauth/callback", {
        method: "POST",
        body: JSON.stringify({ state: oauth.state, code: oauth.code }),
      });
      if (abortIfStale(gen)) return true;
      try {
        sessionStorage.removeItem(OAUTH_PENDING_KEY);
      } catch {
        /* ignore */
      }
      stripOAuthQueryFromUrl();
      return true;
    } catch (err) {
      if (!abortIfStale(gen)) showRecvError(err.message);
      try {
        sessionStorage.removeItem(OAUTH_PENDING_KEY);
      } catch {
        /* ignore */
      }
      stripOAuthQueryFromUrl();
      return false;
    }
  }

  async function refresh() {
    const gen = sessionGeneration;
    const root = $("receptionist-root");
    if (!root) return;
    if (onTokenChangedFromSnapshot()) return;
    if (!readToken() || !window.NovaGrowthSession?.isVerified()) {
      root.innerHTML = `<div class="hint">Sign in to load receptionist status.</div>`;
      return;
    }
    cache.tokenSnapshot = readToken();
    root.innerHTML = `<div class="loading">Loading receptionist status…</div>`;
    clearRecvStatus();
    cache.faqSummary = setupFaqSummaryFromDom();

    const results = await Promise.allSettled([
      api("/api/nova/growth-agent/receptionist/status"),
      api("/api/nova/growth-agent/calendar/sync-errors"),
      api("/api/nova/growth-agent/notifications"),
      api("/api/nova/growth-agent/handoffs"),
      api("/api/nova/growth-agent/receptionist/readiness"),
    ]);

    if (abortIfStale(gen)) return;

    let statusPayload = null;
    if (results[0].status === "fulfilled") {
      statusPayload = results[0].value || {};
      cache.status = statusPayload.agent || statusPayload.status || statusPayload;
      cache.calendar = normalizeCalendar(
        statusPayload.calendar || cache.status.calendar || { connected: false }
      );
    } else {
      cache.status = { paused: false, disabled: false, pilot: true, error: results[0].reason.message };
      cache.calendar = normalizeCalendar({ connected: false });
    }

    cache.syncErrors =
      results[1].status === "fulfilled"
        ? results[1].value.items || results[1].value.errors || results[1].value
        : [];
    cache.notifications =
      results[2].status === "fulfilled"
        ? results[2].value.items || results[2].value.notifications || results[2].value
        : [];
    cache.handoffs =
      results[3].status === "fulfilled"
        ? results[3].value.items || results[3].value.handoffs || results[3].value
        : [];

    if (results[4].status === "fulfilled") {
      cache.readiness = normalizeReadiness(results[4].value);
    } else {
      cache.readiness = extractReadinessFromStatus(statusPayload);
    }

    if (abortIfStale(gen)) return;
    paintPanel();
  }

  function init() {
    window.addEventListener("storage", (event) => {
      if (event.key === TOKEN_KEY && event.newValue !== cache.tokenSnapshot) {
        clearState();
      }
    });

    // Session verification, not a timed login callback, triggers receptionist loading.
    const signOutBtn = $("sign-out");
    if (signOutBtn) {
      signOutBtn.addEventListener("click", () => clearState());
    }
    ["pause-agent", "disable-agent", "resume-agent", "save-setup", "activate-setup"].forEach((id) => {
      const btn = $(id);
      if (btn) btn.addEventListener("click", () => window.setTimeout(() => refresh().catch(() => {}), 600));
    });

    const boot = async () => {
      const gen = sessionGeneration;
      if (onTokenChangedFromSnapshot()) return;
      if (!window.NovaGrowthSession?.isVerified()) {
        const root = $("receptionist-root");
        if (root) root.innerHTML = `<div class="hint">Sign in to load receptionist status.</div>`;
        return;
      }
      if (!readToken()) return;
      try {
        await completeCalendarOAuthIfNeeded();
      } catch {
        /* errors surfaced in receptionist-status */
      }
      if (abortIfStale(gen)) return;
      await refresh().catch(() => clearState());
    };

    window.NovaReceptionist.onAuthenticated = boot;
    // The owner-session controller calls onAuthenticated only after /api/auth/me
    // succeeds. Do not fetch owner data from a merely saved localStorage token.
    if (window.NovaGrowthSession?.isVerified()) boot().catch(() => clearState());
  }

  window.NovaReceptionist = {
    clearState,
    refresh,
    init,
    renderCalendarSection,
    renderReadinessSection,
    renderReceptionistPanel,
    redactForDisplay,
    escapeHtml,
    isCalendarConnected,
    normalizeCalendar,
    normalizeReadiness,
    extractReadinessFromStatus,
    buildVoiceSimulatorPayload,
    _test: {
      getGeneration: () => sessionGeneration,
      setGeneration: (value) => {
        sessionGeneration = Number(value) || 0;
      },
      abortIfStale,
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();