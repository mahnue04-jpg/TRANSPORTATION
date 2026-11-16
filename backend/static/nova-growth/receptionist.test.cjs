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

const helpers = [
  sensitiveKeyLine,
  extractFunction("escapeHtml"),
  extractFunction("redactForDisplay"),
  extractFunction("renderFaqSection"),
  extractFunction("renderAgentStatusSection"),
  extractFunction("renderCalendarSection"),
  extractFunction("renderSyncErrorsSection"),
  extractFunction("renderNotificationsSection"),
  extractFunction("renderHandoffsSection"),
  extractFunction("renderVoiceSimulatorSection"),
  extractFunction("renderReceptionistPanel"),
  extractFunction("clearRecvStatus"),
  extractFunction("clearState"),
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
  };
  const elements = {};
  const element = (id) => {
    if (!elements[id]) {
      elements[id] = { innerHTML: "", textContent: "", className: "hint" };
    }
    return elements[id];
  };
  const ctx = { cache, document: { getElementById: element }, window: {}, localStorage: { getItem: () => "" } };
  vm.createContext(ctx);
  vm.runInContext(`const $ = (id) => document.getElementById(id);\n${helpers}\n${extra}`, ctx);
  return { ctx, elements };
}

test("calendar section shows Not connected when disconnected", () => {
  const { ctx } = runHelpers();
  const html = ctx.renderCalendarSection({ connected: false });
  assert.match(html, /Not connected/);
  assert.doesNotMatch(html, /Connected/);
});

test("sign-out clearState wipes cache and receptionist DOM", () => {
  const { ctx, elements } = runHelpers();
  elements["receptionist-root"] = { innerHTML: "<div>loaded</div>", textContent: "", className: "hint" };
  ctx.cache.status = { paused: true };
  ctx.cache.calendar = { connected: true, calendar_id: "cal-1" };
  ctx.cache.voiceResult = { simulated: true, reply: "ok" };
  ctx.clearState();
  assert.equal(ctx.cache.status, null);
  assert.equal(ctx.cache.calendar, null);
  assert.equal(ctx.cache.voiceResult, null);
  assert.match(elements["receptionist-root"].innerHTML, /cleared/);
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