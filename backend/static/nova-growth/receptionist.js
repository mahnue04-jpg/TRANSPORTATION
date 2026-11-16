(() => {
  const cache = {
    status: null,
    calendar: null,
    syncErrors: null,
    notifications: null,
    handoffs: null,
    voiceResult: null,
    faqSummary: null,
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
    const explicitState = params.get("calendar_oauth_state");
    const explicitCode = params.get("calendar_oauth_code");
    if (explicitState && explicitCode) {
      return { state: explicitState, code: explicitCode };
    }
    const state = params.get("state");
    const code = params.get("code");
    if (state && code && sessionStorage.getItem(OAUTH_PENDING_KEY) === "1") {
      return { state, code };
    }
    return null;
  }

  function stripOAuthQueryFromUrl() {
    const url = new URL(window.location.href);
    ["calendar_oauth_state", "calendar_oauth_code", "state", "code"].forEach((key) => {
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

  function renderReceptionistPanel(data) {
    const status = data && data.status ? data.status : {};
    const calendar = normalizeCalendar(data && data.calendar ? data.calendar : { connected: false });
    return `
      <div class="recv-grid">
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
    if (!readToken()) {
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
    ]);

    if (abortIfStale(gen)) return;

    if (results[0].status === "fulfilled") {
      const payload = results[0].value || {};
      cache.status = payload.agent || payload.status || payload;
      cache.calendar = normalizeCalendar(
        payload.calendar || cache.status.calendar || { connected: false }
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

    if (abortIfStale(gen)) return;
    paintPanel();
  }

  function init() {
    window.addEventListener("storage", (event) => {
      if (event.key === TOKEN_KEY && event.newValue !== cache.tokenSnapshot) {
        clearState();
      }
    });

    const loginForm = $("login-form");
    if (loginForm) {
      loginForm.addEventListener("submit", () => {
        window.setTimeout(() => refresh().catch(() => clearState()), 400);
      });
    }
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
      if (readToken()) {
        try {
          await completeCalendarOAuthIfNeeded();
        } catch {
          /* errors surfaced in receptionist-status */
        }
        if (abortIfStale(gen)) return;
        await refresh().catch(() => clearState());
      } else {
        const root = $("receptionist-root");
        if (root) root.innerHTML = `<div class="hint">Sign in to load receptionist status.</div>`;
      }
    };

    boot().catch(() => clearState());
  }

  window.NovaReceptionist = {
    clearState,
    refresh,
    init,
    renderCalendarSection,
    renderReceptionistPanel,
    redactForDisplay,
    escapeHtml,
    isCalendarConnected,
    normalizeCalendar,
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