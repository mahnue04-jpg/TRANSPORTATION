const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "receptionist.js"), "utf8");

function extractFunction(name) {
  const start = source.indexOf(`  function ${name}(`);
  if (start < 0) throw new Error(`missing ${name}`);
  let depth = 0;
  let i = start;
  let started = false;
  for (; i < source.length; i++) {
    const ch = source[i];
    if (ch === "{") {
      depth += 1;
      started = true;
    } else if (ch === "}") {
      depth -= 1;
      if (started && depth === 0) {
        return source.slice(start, i + 1);
      }
    }
  }
  throw new Error(`unterminated ${name}`);
}

const sensitiveKeyLine = source.slice(
  source.indexOf("const SENSITIVE_KEY"),
  source.indexOf(";", source.indexOf("const SENSITIVE_KEY")) + 1
);

const defaultCalledLine = source.slice(
  source.indexOf("const DEFAULT_CALLED"),
  source.indexOf(";", source.indexOf("const DEFAULT_CALLED")) + 1
);
const defaultCallerLine = source.slice(
  source.indexOf("const DEFAULT_CALLER"),
  source.indexOf(";", source.indexOf("const DEFAULT_CALLER")) + 1
);

const helpers = [
  sensitiveKeyLine,
  defaultCalledLine,
  defaultCallerLine,
  extractFunction("escapeHtml"),
  extractFunction("redactForDisplay"),
  extractFunction("isCalendarConnected"),
  extractFunction("normalizeCalendar"),
  extractFunction("readinessTone"),
  extractFunction("normalizeConnectionState"),
  extractFunction("connectionStateLabel"),
  extractFunction("connectionStateTone"),
  extractFunction("normalizeCredentialHealth"),
  extractFunction("credentialHealthLabel"),
  extractFunction("normalizeSyncQueue"),
  extractFunction("normalizeTwilio"),
  extractFunction("normalizeNotificationsReadiness"),
  extractFunction("normalizeReadiness"),
  extractFunction("extractReadinessFromStatus"),
  extractFunction("buildVoiceSimulatorPayload"),
  extractFunction("renderFaqSection"),
  extractFunction("renderAgentStatusSection"),
  extractFunction("renderCalendarSection"),
  extractFunction("renderSyncErrorsSection"),
  extractFunction("renderNotificationsSection"),
  extractFunction("renderHandoffsSection"),
  extractFunction("renderVoiceSimulatorSection"),
  extractFunction("renderReadinessRecoverableErrors"),
  extractFunction("renderReadinessSection"),
  extractFunction("renderReceptionistPanel"),
  extractFunction("clearRecvStatus"),
].join("\n");

function runHelpers(extra = "") {
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
  const elements = {};
  const element = (id) => {
    if (!elements[id]) {
      elements[id] = { innerHTML: "", textContent: "", className: "hint" };
    }
    return elements[id];
  };
  const ctx = {
    cache,
    sessionGeneration,
    document: { getElementById: element },
    window: {},
    localStorage: { getItem: () => "" },
  };
  vm.createContext(ctx);
  vm.runInContext(
    `const $ = (id) => document.getElementById(id);
let sessionGeneration = 0;
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
    root.innerHTML = '<div class="hint">Signed out — receptionist state cleared.</div>';
  }
  clearRecvStatus();
}
${helpers}
${extra}`,
    ctx
  );
  return { ctx, elements, getGeneration: () => vm.runInContext("sessionGeneration", ctx) };
}

function loadNovaReceptionist(mocks = {}) {
  const elements = {};
  const element = (id) => {
    if (!elements[id]) {
      elements[id] = {
        innerHTML: "",
        textContent: "",
        className: "hint",
        value: "",
        addEventListener: () => {},
        querySelector: () => null,
        querySelectorAll: () => [],
      };
    }
    return elements[id];
  };
  const sessionStore = { ...mocks.sessionStorage };
  const localStore = { amicor_growth_token: mocks.token || "tok-a" };
  const fetchCalls = [];
  const ctx = {
    document: {
      getElementById: element,
      title: "Growth",
      readyState: "loading",
      addEventListener: () => {},
    },
    window: {
      location: { href: mocks.href || "https://example.test/nova/growth", assign: () => {} },
      addEventListener: () => {},
      setTimeout: (fn) => fn(),
      NovaReceptionist: null,
    },
    localStorage: {
      getItem: (k) => localStore[k] ?? null,
      setItem: (k, v) => {
        localStore[k] = v;
      },
    },
    sessionStorage: {
      getItem: (k) => sessionStore[k] ?? null,
      setItem: (k, v) => {
        sessionStore[k] = v;
      },
      removeItem: (k) => {
        delete sessionStore[k];
      },
    },
    history: { replaceState: () => {} },
    fetch: async (url, opts) => {
      fetchCalls.push({ url, opts });
      if (mocks.fetch) return mocks.fetch(url, opts, fetchCalls);
      return { ok: true, text: async () => JSON.stringify({}) };
    },
    console: { error: () => {} },
  };
  vm.createContext(ctx);
  // Strip auto-init but keep the IIFE closer so vm can parse the module.
  const testSource = source.replace(
    /\n  if \(document\.readyState === "loading"\) \{[\s\S]*?\n\}\)\(\);\s*$/,
    "\n})();\n"
  );
  vm.runInContext(testSource, ctx);
  return { Nova: ctx.window.NovaReceptionist, elements, fetchCalls, ctx, sessionStore, localStore };
}

test("calendar section shows Connected and calendar id when connected:true", () => {
  const { ctx } = runHelpers();
  const html = ctx.renderCalendarSection({
    connected: true,
    calendar_id: "cal-primary",
    status: "connected",
  });
  assert.match(html, /Connected/);
  assert.match(html, /cal-primary/);
  assert.doesNotMatch(html, /Not connected/);
});

test("calendar section shows Not connected when disconnected or missing", () => {
  const { ctx } = runHelpers();
  assert.match(ctx.renderCalendarSection({ connected: false }), /Not connected/);
  assert.match(ctx.renderCalendarSection({ status: "Not connected" }), /Not connected/);
  assert.match(ctx.renderCalendarSection(null), /Not connected/);
  assert.match(ctx.renderCalendarSection({ status: "connected" }), /Connected/);
  assert.equal(ctx.isCalendarConnected({ connected: false, status: "connected" }), false);
});

test("sign-out clearState wipes cache, DOM, and bumps session generation", () => {
  const { ctx, elements, getGeneration } = runHelpers();
  elements["receptionist-root"] = { innerHTML: "<div>loaded</div>", textContent: "", className: "hint" };
  const before = getGeneration();
  ctx.cache.status = { paused: true };
  ctx.cache.calendar = { connected: true, calendar_id: "cal-1" };
  ctx.cache.voiceResult = { simulated: true, reply: "ok" };
  ctx.clearState();
  assert.equal(getGeneration(), before + 1);
  assert.equal(ctx.cache.status, null);
  assert.equal(ctx.cache.calendar, null);
  assert.equal(ctx.cache.voiceResult, null);
  assert.match(elements["receptionist-root"].innerHTML, /cleared/);
});

test("voice simulator payload includes called_number and simulated flag", () => {
  const { ctx } = runHelpers();
  const payload = ctx.buildVoiceSimulatorPayload("booking", "Hello", "+15555550100", "+15555550101");
  assert.equal(payload.called_number, "+15555550100");
  assert.equal(payload.caller_number, "+15555550101");
  assert.equal(payload.intent, "booking");
  assert.equal(payload.utterance, "Hello");
  assert.equal(payload.simulated, true);
  const html = ctx.renderVoiceSimulatorSection(null);
  assert.match(html, /recv-voice-called/);
  assert.match(html, /SIMULATED/);
});

test("voice simulator panel is labeled SIMULATED", () => {
  const { ctx } = runHelpers();
  const html = ctx.renderVoiceSimulatorSection(null);
  assert.match(html, /SIMULATED/);
  assert.match(html, /not a live phone/i);
  const panel = ctx.renderReceptionistPanel({
    status: {},
    calendar: { connected: false },
    syncErrors: [],
    notifications: [],
    handoffs: [],
    voiceResult: null,
    faqSummary: { business_name: "Demo", faq_count: 1, hours_preview: "{}" },
  });
  assert.match(panel, /SIMULATED/);
});

test("rendered HTML redacts tokens and never leaks secrets", () => {
  const { ctx } = runHelpers();
  const redacted = ctx.redactForDisplay({
    access_token: "super-secret-access",
    refresh_token: "super-secret-refresh",
    nested: { token: "widget-token-value" },
    calendar: { connected: true, calendar_id: "primary" },
  });
  assert.equal(redacted.access_token, "[redacted]");
  assert.equal(redacted.refresh_token, "[redacted]");
  assert.equal(redacted.nested.token, "[redacted]");
  const panel = ctx.renderReceptionistPanel({
    status: redacted,
    calendar: redacted.calendar,
    syncErrors: [{ state: "failed", message: "quota", operation: "create" }],
    notifications: [],
    handoffs: [],
    voiceResult: { simulated: true, note: "mock booking pending — not externally confirmed" },
    faqSummary: { business_name: "Co", faq_count: 2, hours_preview: "{}" },
  });
  assert.doesNotMatch(panel, /super-secret/);
  assert.doesNotMatch(panel, /widget-token-value/);
  assert.match(panel, /not externally confirmed|Not connected/);
});

test("stale refresh does not repaint after clearState bumps generation", async () => {
  const statusPayload = {
    calendar: { connected: true, calendar_id: "late-cal" },
    agent: { active: true },
  };
  const { Nova, elements } = loadNovaReceptionist({
    fetch: async (url) => {
      if (url.includes("/receptionist/status")) {
        await new Promise((r) => setTimeout(r, 30));
        return { ok: true, text: async () => JSON.stringify(statusPayload) };
      }
      return { ok: true, text: async () => JSON.stringify({ items: [] }) };
    },
  });
  elements["receptionist-root"] = {
    innerHTML: "",
    textContent: "",
    className: "hint",
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
  };
  const gen = Nova._test.getGeneration();
  const refreshPromise = Nova.refresh();
  Nova.clearState();
  await refreshPromise;
  assert.ok(Nova._test.getGeneration() > gen);
  assert.match(elements["receptionist-root"].innerHTML, /cleared/);
  assert.doesNotMatch(elements["receptionist-root"].innerHTML, /late-cal/);
});

test("normalizeReadiness accepts build_readiness API payload shape", () => {
  const { ctx } = runHelpers();
  const normalized = ctx.normalizeReadiness({
    organization_id: "org-1",
    calendar: {
      connected: true,
      status: "connected",
      calendar_id: "primary",
      calendar_summary: "Pilot",
      configuration: { state: "connected", label: "Google Calendar connected" },
      selected_calendar_id: "primary",
      selected_calendar_summary: "Pilot",
      credential_health: {
        state: "healthy",
        has_refresh_credential: true,
        has_access_credential: true,
        access_expires_at: null,
        refresh_needed: false,
      },
    },
    sync_queue: {
      state: "empty",
      label: "Empty queue (not a failure)",
      counts: {},
      pending_or_running: 0,
      failed: 0,
      recoverable_errors: [],
    },
    notifications: {
      state: "empty",
      label: "Empty queue (not a failure)",
      counts: {},
      worker_enabled: true,
      honesty: { provider_accepted_is_not_inbox_receipt: true },
      configuration: { purpose: "transactional_only", adapter: "mock_email" },
    },
    voice: {
      mapping_state: "unmapped",
      label: "No Twilio number mapped for this organization",
      webhook: {
        ready: false,
        live_voice: false,
        simulator_enabled: true,
        label: "SIMULATED — live voice hard-off",
      },
    },
    honesty: { empty_queue_is_not_failure: true },
    pilot_live_ready: false,
  });
  assert.equal(normalized.calendar.connection_state, "connected");
  assert.equal(normalized.calendar.calendar_id, "primary");
  assert.equal(normalized.calendar.credential_health, "healthy");
  assert.equal(normalized.sync_queue.empty, true);
  assert.equal(normalized.twilio.mapping, "unmapped");
  assert.equal(normalized.twilio.mode, "simulator");
  const html = ctx.renderReadinessSection(normalized);
  assert.match(html, /Empty queue \(not a failure\)/);
  assert.match(html, /SIMULATED/);
  assert.match(html, /primary/);
  assert.doesNotMatch(html, /refresh_token|access_token/);
});

test("readiness section labels missing config, empty queue, and SIMULATED twilio", () => {
  const { ctx } = runHelpers();
  const html = ctx.renderReadinessSection(
    ctx.normalizeReadiness({
      calendar: {
        connection_state: "missing_config",
        configured: false,
        calendar_id: null,
        calendar_summary: null,
        credential_health: "missing_refresh",
      },
      sync_queue: { pending: 0, failed: 0, running: 0, recoverable_errors: [] },
      notifications: {
        configured: false,
        delivery_state: "provider_accepted",
      },
      twilio: { mapping: "unmapped", webhook_ready: false, mode: "simulator", simulated: true },
    })
  );
  assert.match(html, /Missing configuration/);
  assert.match(html, /Empty queue \(not a failure\)/);
  assert.match(html, /Missing refresh/);
  assert.match(html, /provider_accepted \(not inbox receipt\)/);
  assert.match(html, /Unmapped/);
  assert.match(html, /SIMULATED/);
  assert.doesNotMatch(html, /access_token|refresh_token|ya29\./i);
});

test("readiness distinguishes connected calendar and failed sync queue", () => {
  const { ctx } = runHelpers();
  const html = ctx.renderReadinessSection(
    ctx.normalizeReadiness({
      calendar: {
        connection_state: "connected",
        configured: true,
        calendar_id: "cal-primary",
        calendar_summary: "Front desk",
        credential_health: "healthy",
      },
      sync_queue: {
        pending: 1,
        failed: 2,
        running: 0,
        recoverable_errors: [{ code: "TIMEOUT_AFTER_WRITE", message: "retryable" }],
      },
      notifications: { configured: true, delivery_state: "queued" },
      twilio: { mapping: "mapped", webhook_ready: true, mode: "live_off" },
    })
  );
  assert.match(html, /Connected/);
  assert.match(html, /cal-primary/);
  assert.match(html, /Front desk/);
  assert.match(html, /Healthy/);
  assert.match(html, /Queue has failures/);
  assert.match(html, /TIMEOUT_AFTER_WRITE/);
  assert.match(html, /Mapped/);
  assert.match(html, /Live-off/);
  assert.doesNotMatch(html, /Empty queue/);
});

test("readiness shows Not connected and Unverified when payload incomplete", () => {
  const { ctx } = runHelpers();
  assert.match(ctx.renderReadinessSection(null), /Unverified/);
  const html = ctx.renderReadinessSection(
    ctx.normalizeReadiness({
      calendar: { connection_state: "disconnected" },
      sync_queue: {},
      notifications: {},
      twilio: {},
    })
  );
  assert.match(html, /Not connected/);
  assert.match(html, /Unverified/);
});

test("readiness redacts secrets before render", () => {
  const { ctx } = runHelpers();
  const redacted = ctx.redactForDisplay({
    calendar: {
      connection_state: "needs_reconnect",
      calendar_id: "cal-1",
      access_token: "secret-access",
      refresh_token: "secret-refresh",
      credential_health: "expired",
    },
    sync_queue: { pending: 0, failed: 0, running: 0 },
    notifications: { configured: true, delivery_state: "failed", token: "notify-secret" },
    twilio: { mapping: "mapped", mode: "simulator", auth_token: "twilio-secret" },
  });
  const html = ctx.renderReadinessSection(ctx.normalizeReadiness(redacted));
  assert.doesNotMatch(html, /secret-access|secret-refresh|notify-secret|twilio-secret/);
  assert.match(html, /Needs reconnect|Expired|SIMULATED/);
  assert.equal(redacted.calendar.access_token, "[redacted]");
  assert.equal(redacted.calendar.refresh_token, "[redacted]");
  assert.equal(redacted.notifications.token, "[redacted]");
});

test("refresh prefers readiness endpoint and falls back to status readiness key", async () => {
  const readinessPayload = {
    calendar: {
      connection_state: "connected",
      calendar_id: "ready-cal",
      credential_health: "healthy",
      configured: true,
    },
    sync_queue: { pending: 0, failed: 0, running: 0 },
    notifications: { configured: true, delivery_state: "queued" },
    twilio: { mapping: "mapped", webhook_ready: true, mode: "simulator", simulated: true },
  };
  const { Nova, elements, fetchCalls } = loadNovaReceptionist({
    fetch: async (url) => {
      if (url.includes("/receptionist/readiness")) {
        return { ok: true, text: async () => JSON.stringify(readinessPayload) };
      }
      if (url.includes("/receptionist/status")) {
        return {
          ok: true,
          text: async () =>
            JSON.stringify({
              calendar: { connected: true, calendar_id: "status-cal" },
              agent: { active: true },
            }),
        };
      }
      return { ok: true, text: async () => JSON.stringify({ items: [] }) };
    },
  });
  // Prefetch root via getElementById so querySelector stubs exist.
  elements["receptionist-root"];
  await Nova.refresh();
  assert.ok(fetchCalls.some((c) => String(c.url).includes("/receptionist/readiness")));
  assert.match(elements["receptionist-root"].innerHTML, /ready-cal/);
  assert.match(elements["receptionist-root"].innerHTML, /data-recv-readiness/);
  assert.match(elements["receptionist-root"].innerHTML, /SIMULATED/);

  const fallback = loadNovaReceptionist({
    fetch: async (url) => {
      if (url.includes("/receptionist/readiness")) {
        return { ok: false, statusText: "Not Found", text: async () => JSON.stringify({ detail: "missing" }) };
      }
      if (url.includes("/receptionist/status")) {
        return {
          ok: true,
          text: async () =>
            JSON.stringify({
              calendar: { connected: false, status: "Not connected" },
              agent: { active: true },
              readiness: {
                calendar: {
                  connection_state: "revoked",
                  calendar_id: "embed-cal",
                  credential_health: "expired",
                },
                sync_queue: { pending: 0, failed: 0, running: 0 },
                notifications: { configured: false, delivery_state: "Unverified" },
                twilio: { mapping: "unmapped", mode: "live_off" },
              },
            }),
        };
      }
      return { ok: true, text: async () => JSON.stringify({ items: [] }) };
    },
  });
  fallback.elements["receptionist-root"];
  await fallback.Nova.refresh();
  assert.match(fallback.elements["receptionist-root"].innerHTML, /embed-cal/);
  assert.match(fallback.elements["receptionist-root"].innerHTML, /Revoked/);
  assert.match(fallback.elements["receptionist-root"].innerHTML, /Not connected/);
});