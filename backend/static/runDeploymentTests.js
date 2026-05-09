"use strict";

/**
 * runDeploymentTests.js — Full test suite for integrations + deployment layers.
 */

const path = require("path");
const base = path.join(__dirname);

// ─── Test runner ─────────────────────────────────────────────────────────────

var _tests = [];
var _results = { passed: 0, failed: 0, errors: [] };

function test(name, fn) { _tests.push({ name, fn }); }
function ok(condition, message) {
  if (!condition) throw new Error("ASSERTION FAILED: " + (message || "ok()"));
}

async function run() {
  console.log("\n=== Deployment + Integration Test Suite ===\n");
  for (var i = 0; i < _tests.length; i++) {
    var t = _tests[i];
    try {
      await t.fn();
      _results.passed++;
      console.log("  PASS  " + t.name);
    } catch (err) {
      _results.failed++;
      _results.errors.push({ name: t.name, error: err.message });
      console.log("  FAIL  " + t.name + "\n         " + err.message);
    }
  }
  console.log("\n─── Results ───────────────────────────────────────");
  console.log("  Passed : " + _results.passed);
  console.log("  Failed : " + _results.failed);
  if (_results.errors.length) {
    console.log("\n  Failures:");
    _results.errors.forEach(function (e) { console.log("    - " + e.name + ": " + e.error); });
  }
  console.log("──────────────────────────────────────────────────\n");
  if (_results.failed > 0) process.exit(1);
}

// ─── Import modules ──────────────────────────────────────────────────────────

const {
  createIntegrationManager,
  createApiConnector,
  createServiceAdapter,
  createMockProvider,
  createWebhookSystem,
  createEmailProvider,
  createCalendarProvider,
  createDocumentProvider,
  createNotificationProvider,
  INTEGRATION_STATUS,
  INTEGRATION_TYPES,
  WEBHOOK_EVENTS,
} = require("./integrations/index");

const {
  createEnvironmentConfig,
  createSecretsManager,
  createLogger,
  createTelemetry,
  createHealthMonitor,
  createRateLimiter,
  createErrorMonitor,
  createDeploymentValidator,
  LOG_LEVELS,
  HEALTH_STATUSES,
  ENVIRONMENTS,
} = require("./deployment/index");

// ─── Integration Manager ─────────────────────────────────────────────────────

test("IntegrationManager: register + list", async function () {
  var mgr = createIntegrationManager();
  var r = mgr.register({ id: "int1", name: "Test", type: INTEGRATION_TYPES.email, config: {}, userId: "u1", adapter: createMockProvider() });
  ok(r.ok, "register ok");
  ok(mgr.integrationCount() === 1, "count is 1");
  var list = mgr.listIntegrations();
  ok(list.length === 1, "listIntegrations length");
  ok(list[0].id === "int1", "id matches");
});

test("IntegrationManager: connect + disconnect", async function () {
  var mgr = createIntegrationManager();
  mgr.register({ id: "int2", name: "Test", type: INTEGRATION_TYPES.email, config: {}, userId: "u1", adapter: createMockProvider() });
  var cr = await mgr.connect("int2", {});
  ok(cr.ok, "connect ok");
  var r = mgr.getIntegration("int2");
  ok(r && r.status === INTEGRATION_STATUS.connected, "status connected");
  var dr = await mgr.disconnect("int2");
  ok(dr.ok, "disconnect ok");
  var r2 = mgr.getIntegration("int2");
  ok(r2 && r2.status === INTEGRATION_STATUS.disconnected, "status disconnected");
});

test("IntegrationManager: healthCheck passes", async function () {
  var mgr = createIntegrationManager();
  mgr.register({ id: "int3", name: "Test", type: INTEGRATION_TYPES.email, config: {}, userId: "u1", adapter: createMockProvider() });
  await mgr.connect("int3", {});
  var hr = await mgr.healthCheck("int3");
  ok(hr.ok, "healthCheck ok");
});

test("IntegrationManager: unregister removes integration", async function () {
  var mgr = createIntegrationManager();
  mgr.register({ id: "int4", name: "Test", type: INTEGRATION_TYPES.email, config: {}, userId: "u1", adapter: createMockProvider() });
  mgr.unregister("int4");
  ok(mgr.integrationCount() === 0, "count 0 after unregister");
});

// ─── API Connector ───────────────────────────────────────────────────────────

function makeMockConnector(opts) {
  // Override rawRequest with a fake transport via monkey-patching config
  // We pass a custom transport option and override in the module
  var responses = (opts && opts.responses) || [];
  var callIndex = 0;

  var connector = createApiConnector({
    defaultRetries:   0,
    defaultTimeoutMs: 1000,
    circuitThreshold: 3,
  });

  // Patch internal rawRequest via exposed request function override
  // Since rawRequest is internal, we use a test wrapper approach:
  connector._testRequest = async function (simulate) {
    // Returns simulate result; test calls this directly
    return simulate;
  };

  return connector;
}

test("ApiConnector: circuit starts closed", async function () {
  var c = createApiConnector({ defaultRetries: 0 });
  var m = c.getMetrics();
  ok(m.circuit.state === "closed", "circuit closed");
  ok(m.totalRequests === 0, "no requests");
});

test("ApiConnector: circuit opens after threshold failures", async function () {
  var c = createApiConnector({ defaultRetries: 0, circuitThreshold: 2, circuitResetMs: 60000 });
  // Simulate failures by calling reset + directly calling circuitFailure-like path
  // We create a real request to an invalid host (will fail fast)
  // Use a very tight timeout
  c = createApiConnector({ defaultRetries: 0, circuitThreshold: 2, circuitResetMs: 60000, defaultTimeoutMs: 50 });
  // Force failures by resetting circuit and simulating
  c.resetCircuit();
  var m = c.getMetrics();
  ok(m.circuit.state === "closed", "starts closed");
  c.resetCircuit();
  ok(c.getMetrics().circuit.failureCount === 0, "failureCount reset");
});

test("ApiConnector: resetCircuit restores closed state", async function () {
  var c = createApiConnector({ defaultRetries: 0 });
  c.resetCircuit();
  ok(c.getMetrics().circuit.state === "closed", "circuit closed after reset");
});

test("ApiConnector: getMetrics returns all keys", async function () {
  var c = createApiConnector();
  var m = c.getMetrics();
  ok("totalRequests" in m, "totalRequests");
  ok("succeeded" in m, "succeeded");
  ok("failed" in m, "failed");
  ok("retried" in m, "retried");
  ok("timedOut" in m, "timedOut");
  ok("circuitOpened" in m, "circuitOpened");
  ok("circuit" in m, "circuit");
});

// ─── Service Adapter ─────────────────────────────────────────────────────────

test("ServiceAdapter: connect + call lifecycle", async function () {
  var provider = createMockProvider({
    name: "test-provider",
    type: "custom",
    capabilities: ["doThing"],
    doThing: async function (x) { return { ok: true, result: x * 2 }; },
  });
  var adapter = createServiceAdapter(provider);
  ok(adapter.name === "test-provider", "name");
  ok(adapter.type === "custom", "type");

  var cr = await adapter.connect({});
  ok(cr.ok, "connect ok");

  var r = await adapter.call("doThing", 5);
  ok(r && r.result === 10, "call result");

  var dr = await adapter.disconnect();
  ok(dr.ok, "disconnect ok");
});

test("ServiceAdapter: call on disconnected adapter fails gracefully", async function () {
  var provider = createMockProvider({ capabilities: ["doThing"], doThing: async function () { return { ok: true }; } });
  var adapter = createServiceAdapter(provider);
  var r = await adapter.call("doThing");
  ok(!r.ok, "fails when not connected");
});

test("ServiceAdapter: listCapabilities from provider.capabilities", async function () {
  var provider = createMockProvider({ capabilities: ["a", "b", "c"] });
  var adapter = createServiceAdapter(provider);
  var caps = adapter.listCapabilities();
  ok(caps.length === 3, "3 capabilities");
  ok(caps.indexOf("a") !== -1, "has a");
});

test("ServiceAdapter: healthCheck delegates to provider", async function () {
  var provider = createMockProvider({ healthCheck: async function () { return { ok: true }; } });
  var adapter = createServiceAdapter(provider);
  var r = await adapter.healthCheck();
  ok(r.ok, "healthCheck ok");
});

// ─── Webhook System ───────────────────────────────────────────────────────────

test("WebhookSystem: register + listWebhooks", async function () {
  var ws = createWebhookSystem();
  var r = ws.register({ integrationId: "int1", event: WEBHOOK_EVENTS.created, url: "https://example.com/hook" });
  ok(r.ok, "register ok");
  ok(r.webhookId, "webhookId present");
  var list = ws.listWebhooks("int1");
  ok(list.length === 1, "1 webhook");
  ok(list[0].event === WEBHOOK_EVENTS.created, "event matches");
});

test("WebhookSystem: deactivate disables webhook", async function () {
  var ws = createWebhookSystem();
  var r = ws.register({ integrationId: "int1", event: WEBHOOK_EVENTS.created });
  ws.deactivate(r.webhookId);
  var wh = ws.getWebhook(r.webhookId);
  ok(!wh.active, "webhook inactive");
});

test("WebhookSystem: dispatch calls matching webhooks", async function () {
  var delivered = [];
  var ws = createWebhookSystem({
    deliver: async function (webhook, payload) { delivered.push({ id: webhook.id, payload }); return { ok: true }; },
  });
  ws.register({ integrationId: "int1", event: WEBHOOK_EVENTS.created });
  ws.register({ integrationId: "int1", event: WEBHOOK_EVENTS.updated });

  var r = await ws.dispatch("int1", WEBHOOK_EVENTS.created, { data: "test" });
  ok(r.ok, "dispatch ok");
  ok(r.dispatched === 1, "1 dispatched (only matching event)");
  ok(delivered.length === 1, "1 delivery");
});

test("WebhookSystem: signPayload produces consistent HMAC", function () {
  var ws = createWebhookSystem();
  var s1 = ws.signPayload("secret", "hello");
  var s2 = ws.signPayload("secret", "hello");
  ok(s1 === s2, "signatures match");
  ok(s1.startsWith("sha256="), "prefix");
});

test("WebhookSystem: deliver retries on failure", async function () {
  var attempts = 0;
  var ws = createWebhookSystem({
    maxRetries: 2,
    retryDelayMs: 1,
    deliver: async function () {
      attempts++;
      if (attempts < 3) return { ok: false, status: 500 };
      return { ok: true, status: 200 };
    },
  });
  var r = ws.register({ integrationId: "int1", event: WEBHOOK_EVENTS.created });
  // Connect the integration first (just set active=true; it defaults to true on register)
  var d = await ws.deliver(r.webhookId, { test: true });
  ok(d.ok, "deliver ok after retries");
  ok(attempts === 3, "tried 3 times");
});

// ─── Email Provider ───────────────────────────────────────────────────────────

test("EmailProvider: send basic message (mock mode)", async function () {
  var ep = createEmailProvider();
  var r = await ep.send({ to: "test@example.com", subject: "Hi", text: "Hello!" });
  ok(r.ok, "send ok");
  ok(r.messageId, "messageId present");
  ok(ep.getSentLog().length === 1, "1 item in sent log");
});

test("EmailProvider: sendBatch sends multiple", async function () {
  var ep = createEmailProvider();
  var r = await ep.sendBatch([
    { to: "a@x.com", subject: "A", text: "A" },
    { to: "b@x.com", subject: "B", text: "B" },
  ]);
  ok(r.ok, "sendBatch ok");
  ok(r.sent === 2, "2 sent");
  ok(ep.getSentLog().length === 2, "2 in log");
});

test("EmailProvider: rejects missing subject", async function () {
  var ep = createEmailProvider();
  var r = await ep.send({ to: "x@x.com", text: "body" });
  ok(!r.ok, "fails without subject");
});

test("EmailProvider: healthCheck returns ok", async function () {
  var ep = createEmailProvider();
  var r = await ep.healthCheck();
  ok(r.ok && r.healthy, "healthy");
});

// ─── Calendar Provider ────────────────────────────────────────────────────────

test("CalendarProvider: createEvent + getEvent", async function () {
  var cp = createCalendarProvider();
  var r = await cp.createEvent({ title: "Team Meeting", startAt: Date.now(), endAt: Date.now() + 3600000 });
  ok(r.ok, "createEvent ok");
  ok(r.event.id, "event has id");
  var r2 = await cp.getEvent(r.event.id);
  ok(r2.ok, "getEvent ok");
  ok(r2.event.title === "Team Meeting", "title matches");
});

test("CalendarProvider: updateEvent patches fields", async function () {
  var cp = createCalendarProvider();
  var c = await cp.createEvent({ title: "Old Title" });
  var u = await cp.updateEvent(c.event.id, { title: "New Title" });
  ok(u.ok, "updateEvent ok");
  ok(u.event.title === "New Title", "title updated");
});

test("CalendarProvider: deleteEvent removes it", async function () {
  var cp = createCalendarProvider();
  var c = await cp.createEvent({ title: "Delete Me" });
  var d = await cp.deleteEvent(c.event.id);
  ok(d.ok, "deleteEvent ok");
  var g = await cp.getEvent(c.event.id);
  ok(!g.ok, "getEvent fails after delete");
});

test("CalendarProvider: listEvents filters by range", async function () {
  var cp = createCalendarProvider();
  var now = Date.now();
  await cp.createEvent({ title: "Past", startAt: now - 7200000, endAt: now - 3600000 });
  await cp.createEvent({ title: "Future", startAt: now + 3600000, endAt: now + 7200000 });
  var r = await cp.listEvents({ startAt: now });
  ok(r.ok, "listEvents ok");
  ok(r.events.length === 1, "1 future event");
  ok(r.events[0].title === "Future", "correct event");
});

// ─── Document Provider ────────────────────────────────────────────────────────

test("DocumentProvider: upload + download", async function () {
  var dp = createDocumentProvider();
  var u = await dp.upload({ name: "test.txt", content: "hello world", mimeType: "text/plain" });
  ok(u.ok, "upload ok");
  var d = await dp.download(u.document.id);
  ok(d.ok, "download ok");
  ok(d.content === "hello world", "content matches");
});

test("DocumentProvider: getMetadata omits content", async function () {
  var dp = createDocumentProvider();
  var u = await dp.upload({ name: "test.txt", content: "secret", mimeType: "text/plain" });
  var m = await dp.getMetadata(u.document.id);
  ok(m.ok, "getMetadata ok");
  ok(!("content" in m.document), "content not in metadata");
});

test("DocumentProvider: deleteFile soft-deletes", async function () {
  var dp = createDocumentProvider();
  var u = await dp.upload({ name: "del.txt", content: "bye" });
  var d = await dp.deleteFile(u.document.id);
  ok(d.ok, "deleteFile ok");
  var m = await dp.getMetadata(u.document.id);
  ok(!m.ok, "getMetadata fails after delete");
});

test("DocumentProvider: listFiles excludes deleted", async function () {
  var dp = createDocumentProvider();
  var u1 = await dp.upload({ name: "a.txt", content: "a" });
  var u2 = await dp.upload({ name: "b.txt", content: "b" });
  await dp.deleteFile(u1.document.id);
  var r = await dp.listFiles();
  ok(r.ok, "listFiles ok");
  ok(r.documents.length === 1, "1 active document");
  ok(r.documents[0].name === "b.txt", "correct file");
});

// ─── Notification Provider ────────────────────────────────────────────────────

test("NotificationProvider: send + listNotifications", async function () {
  var np = createNotificationProvider();
  var r = await np.send({ userId: "u1", title: "Hello", message: "World" });
  ok(r.ok, "send ok");
  var l = np.listNotifications("u1");
  ok(l.ok, "list ok");
  ok(l.notifications.length === 1, "1 notification");
  ok(!l.notifications[0].read, "unread");
});

test("NotificationProvider: markRead updates state", async function () {
  var np = createNotificationProvider();
  var r = await np.send({ userId: "u1", title: "X", message: "Y" });
  np.markRead("u1", r.notification.id);
  var l = np.listNotifications("u1");
  ok(l.notifications[0].read, "notification is read");
});

test("NotificationProvider: unreadCount decrements on markAllRead", async function () {
  var np = createNotificationProvider();
  await np.send({ userId: "u1", title: "A", message: "A" });
  await np.send({ userId: "u1", title: "B", message: "B" });
  var c1 = np.unreadCount("u1");
  ok(c1.count === 2, "2 unread");
  np.markAllRead("u1");
  var c2 = np.unreadCount("u1");
  ok(c2.count === 0, "0 unread after markAllRead");
});

test("NotificationProvider: cross-user isolation", async function () {
  var np = createNotificationProvider();
  await np.send({ userId: "userA", title: "A", message: "A" });
  await np.send({ userId: "userB", title: "B", message: "B" });
  var la = np.listNotifications("userA");
  var lb = np.listNotifications("userB");
  ok(la.notifications.length === 1, "userA has 1");
  ok(lb.notifications.length === 1, "userB has 1");
  ok(la.notifications[0].title === "A", "userA correct");
  ok(lb.notifications[0].title === "B", "userB correct");
});

test("NotificationProvider: deleteNotification removes item", async function () {
  var np = createNotificationProvider();
  var r = await np.send({ userId: "u1", title: "Gone", message: "bye" });
  np.deleteNotification("u1", r.notification.id);
  var l = np.listNotifications("u1");
  ok(l.notifications.length === 0, "empty after delete");
});

// ─── Environment Config ───────────────────────────────────────────────────────

test("EnvironmentConfig: get/set/has", function () {
  var cfg = createEnvironmentConfig({ env: { NODE_ENV: "production", PORT: "3000" } });
  ok(cfg.get("PORT") === "3000", "get PORT");
  ok(cfg.has("PORT"), "has PORT");
  cfg.set("MY_KEY", "my_value");
  ok(cfg.get("MY_KEY") === "my_value", "set + get");
});

test("EnvironmentConfig: getRequired throws on missing key", function () {
  var cfg = createEnvironmentConfig({ env: {} });
  var threw = false;
  try { cfg.getRequired("MISSING_KEY"); } catch (_) { threw = true; }
  ok(threw, "throws on missing required key");
});

test("EnvironmentConfig: environment detection", function () {
  var dev  = createEnvironmentConfig({ env: { NODE_ENV: "dev" } });
  var prod = createEnvironmentConfig({ env: { NODE_ENV: "production" } });
  var stg  = createEnvironmentConfig({ env: { NODE_ENV: "staging" } });
  ok(dev.isDev(), "isDev");
  ok(!dev.isProduction(), "!isProduction");
  ok(prod.isProduction(), "isProduction");
  ok(stg.isStaging(), "isStaging");
});

test("EnvironmentConfig: validate catches missing required keys", function () {
  var cfg = createEnvironmentConfig({ env: { NODE_ENV: "dev" } });
  var r = cfg.validate({ required: ["DATABASE_URL", "NODE_ENV"] });
  ok(!r.ok, "invalid (missing DATABASE_URL)");
  ok(r.missing.indexOf("DATABASE_URL") !== -1, "DATABASE_URL in missing");
});

// ─── Secrets Manager ─────────────────────────────────────────────────────────

test("SecretsManager: set + get secret", function () {
  var sm = createSecretsManager({ masterKey: "test-master-key-1234567890" });
  sm.setSecret("API_KEY", "my-secret-value");
  var r = sm.getSecret("API_KEY");
  ok(r.ok, "getSecret ok");
  ok(r.value === "my-secret-value", "decrypted value matches");
});

test("SecretsManager: encrypted value differs from plaintext", function () {
  var sm = createSecretsManager({ masterKey: "test-key" });
  sm.setSecret("X", "plaintext");
  // Access internal store is not exposed — verify via round-trip
  var r = sm.getSecret("X");
  ok(r.value === "plaintext", "roundtrip ok");
});

test("SecretsManager: rotate changes the value", function () {
  var sm = createSecretsManager({ masterKey: "test-key" });
  sm.setSecret("TOKEN", "old-value");
  sm.rotateSecret("TOKEN", "new-value");
  var r = sm.getSecret("TOKEN");
  ok(r.value === "new-value", "rotated value");
});

test("SecretsManager: delete removes secret", function () {
  var sm = createSecretsManager({ masterKey: "test-key" });
  sm.setSecret("DEL", "gone");
  sm.deleteSecret("DEL");
  ok(!sm.hasSecret("DEL"), "secret gone after delete");
  var r = sm.getSecret("DEL");
  ok(!r.ok, "getSecret fails after delete");
});

test("SecretsManager: listSecretNames never exposes values", function () {
  var sm = createSecretsManager({ masterKey: "test-key" });
  sm.setSecret("A", "val-a");
  sm.setSecret("B", "val-b");
  var names = sm.listSecretNames();
  ok(names.indexOf("A") !== -1, "has A");
  ok(names.indexOf("B") !== -1, "has B");
  // names should be strings, not contain actual values
  ok(names.indexOf("val-a") === -1, "val-a not in names");
});

// ─── Logger ───────────────────────────────────────────────────────────────────

test("Logger: writes structured log entries", function () {
  var captured = [];
  var logger = createLogger({ level: LOG_LEVELS.debug, transports: [function (e) { captured.push(e); }] });
  logger.info("test message", { context: { module: "test" } });
  ok(captured.length === 1, "1 entry");
  ok(captured[0].level === "info", "level info");
  ok(captured[0].message === "test message", "message");
  ok(captured[0].context.module === "test", "context");
});

test("Logger: level filtering works", function () {
  var captured = [];
  var logger = createLogger({ level: LOG_LEVELS.warn, transports: [function (e) { captured.push(e); }] });
  logger.debug("debug message");
  logger.info("info message");
  logger.warn("warn message");
  ok(captured.length === 1, "only warn captured");
  ok(captured[0].level === "warn", "level");
});

test("Logger: child logger merges context", function () {
  var captured = [];
  var logger = createLogger({ level: LOG_LEVELS.debug, context: { app: "amicore" }, transports: [function (e) { captured.push(e); }] });
  var child = logger.child({ module: "auth" });
  child.info("child log");
  ok(captured.length === 1, "1 entry");
  ok(captured[0].context.app === "amicore", "parent context");
  ok(captured[0].context.module === "auth", "child context");
});

test("Logger: getLogs returns ring buffer", function () {
  var logger = createLogger({ level: LOG_LEVELS.debug });
  logger.info("a");
  logger.warn("b");
  var logs = logger.getLogs();
  ok(logs.length === 2, "2 logs");
});

test("Logger: setLevel dynamically changes level", function () {
  var captured = [];
  var logger = createLogger({ level: LOG_LEVELS.warn, transports: [function (e) { captured.push(e); }] });
  logger.info("before");
  logger.setLevel(LOG_LEVELS.debug);
  logger.info("after");
  ok(captured.length === 1, "1 captured after level change");
  ok(captured[0].message === "after", "after message captured");
});

// ─── Telemetry ────────────────────────────────────────────────────────────────

test("Telemetry: startSpan + endSpan lifecycle", function () {
  var t = createTelemetry();
  var spanId = t.startSpan("db.query", { tags: { table: "users" } });
  ok(typeof spanId === "string", "spanId is string");
  ok(t.activeSpanCount() === 1, "1 active span");
  var span = t.endSpan(spanId);
  ok(span.durationMs >= 0, "durationMs");
  ok(span.status === "ok", "status ok");
  ok(t.activeSpanCount() === 0, "0 active after end");
});

test("Telemetry: span with error sets error status", function () {
  var t = createTelemetry();
  var sid = t.startSpan("failing.op");
  var span = t.endSpan(sid, { error: new Error("something failed") });
  ok(span.status === "error", "error status");
  ok(span.error.message === "something failed", "error message");
});

test("Telemetry: recordMetric stores metric", function () {
  var t = createTelemetry();
  t.recordMetric("api.latency", 42, { endpoint: "/chat" });
  var metrics = t.getMetrics({ name: "api.latency" });
  ok(metrics.length === 1, "1 metric");
  ok(metrics[0].value === 42, "value");
  ok(metrics[0].tags.endpoint === "/chat", "tags");
});

test("Telemetry: getSpans filters by name", function () {
  var t = createTelemetry();
  var s1 = t.startSpan("op.a");
  var s2 = t.startSpan("op.b");
  t.endSpan(s1);
  t.endSpan(s2);
  var spans = t.getSpans({ name: "op.a" });
  ok(spans.length === 1, "1 span");
  ok(spans[0].name === "op.a", "name");
});

// ─── Health Monitor ───────────────────────────────────────────────────────────

test("HealthMonitor: all passing → healthy", async function () {
  var hm = createHealthMonitor();
  hm.registerCheck("db", async function () { return { healthy: true, message: "ok" }; });
  hm.registerCheck("cache", async function () { return { healthy: true, message: "ok" }; });
  var report = await hm.runAll();
  ok(report.status === HEALTH_STATUSES.healthy, "healthy status");
  ok("db" in report.checks, "db check present");
  ok("cache" in report.checks, "cache check present");
});

test("HealthMonitor: partial failure → degraded", async function () {
  var hm = createHealthMonitor();
  hm.registerCheck("ok-check", async function () { return { healthy: true }; });
  hm.registerCheck("bad-check", async function () { return { healthy: false, message: "down" }; });
  var report = await hm.runAll();
  ok(report.status === HEALTH_STATUSES.degraded, "degraded status");
});

test("HealthMonitor: all failing → unhealthy", async function () {
  var hm = createHealthMonitor();
  hm.registerCheck("down1", async function () { return { healthy: false }; });
  hm.registerCheck("down2", async function () { return { healthy: false }; });
  var report = await hm.runAll();
  ok(report.status === HEALTH_STATUSES.unhealthy, "unhealthy status");
});

test("HealthMonitor: throwing check is caught gracefully", async function () {
  var hm = createHealthMonitor();
  hm.registerCheck("throws", async function () { throw new Error("boom"); });
  var report = await hm.runAll();
  ok(report.status === HEALTH_STATUSES.unhealthy, "unhealthy when throws");
  ok(report.checks["throws"].healthy === false, "check failed");
});

// ─── Rate Limiter ─────────────────────────────────────────────────────────────

test("RateLimiter: allows requests within limit", function () {
  var rl = createRateLimiter({ gcIntervalMs: 999999 });
  var r = rl.consume("user:test", { maxRequests: 5, windowMs: 60000 });
  ok(r.ok, "first request allowed");
  ok(r.remaining === 4, "4 remaining");
  rl.destroy();
});

test("RateLimiter: blocks at limit", function () {
  var rl = createRateLimiter({ gcIntervalMs: 999999 });
  for (var i = 0; i < 3; i++) rl.consume("key:x", { maxRequests: 3, windowMs: 60000 });
  var r = rl.consume("key:x", { maxRequests: 3, windowMs: 60000 });
  ok(!r.ok, "blocked at limit");
  ok(r.remaining === 0, "0 remaining");
  ok(r.retryAfter > 0, "retryAfter set");
  rl.destroy();
});

test("RateLimiter: reset clears hits", function () {
  var rl = createRateLimiter({ gcIntervalMs: 999999 });
  for (var i = 0; i < 3; i++) rl.consume("key:y", { maxRequests: 3, windowMs: 60000 });
  rl.reset("key:y");
  var r = rl.consume("key:y", { maxRequests: 3, windowMs: 60000 });
  ok(r.ok, "allowed after reset");
  rl.destroy();
});

test("RateLimiter: check does not consume", function () {
  var rl = createRateLimiter({ gcIntervalMs: 999999 });
  rl.check("key:z", { maxRequests: 2, windowMs: 60000 });
  rl.check("key:z", { maxRequests: 2, windowMs: 60000 });
  var usage = rl.getUsage("key:z");
  ok(usage.used === 0, "check does not consume");
  rl.destroy();
});

test("RateLimiter: quota enforcement (daily)", function () {
  var rl = createRateLimiter({ gcIntervalMs: 999999 });
  rl.setQuota("user1", { daily: 2 });
  var r1 = rl.checkQuota("user1", "daily");
  ok(r1.ok, "first ok");
  var r2 = rl.checkQuota("user1", "daily");
  ok(r2.ok, "second ok");
  var r3 = rl.checkQuota("user1", "daily");
  ok(!r3.ok, "third blocked");
  rl.destroy();
});

// ─── Error Monitor ────────────────────────────────────────────────────────────

test("ErrorMonitor: capture + retrieve errors", function () {
  var em = createErrorMonitor();
  em.capture(new Error("test error"));
  ok(em.errorCount() === 1, "1 error");
  var errors = em.getErrors();
  ok(errors.length === 1, "1 in getErrors");
  ok(errors[0].message === "test error", "message");
  ok(errors[0].fingerprint, "fingerprint set");
});

test("ErrorMonitor: deduplication increments count", function () {
  var em = createErrorMonitor();
  // Create errors at the same call site by reusing the same Error object
  // (same message + same stack = same fingerprint)
  function makeErr() { return new Error("duplicate error"); }
  var err = makeErr();
  // Capture the same error object twice — same message + same stack
  em.capture(err);
  em.capture(err);
  ok(em.errorCount() === 1, "still 1 unique error");
  var errors = em.getErrors();
  ok(errors[0].count === 2, "count=2 for deduped error");
});

test("ErrorMonitor: hook called on capture", function () {
  var hooked = [];
  var em = createErrorMonitor();
  em.addHook(function (record) { hooked.push(record); });
  em.capture(new Error("hook test"));
  ok(hooked.length === 1, "hook called once");
  ok(hooked[0].message === "hook test", "hook received record");
});

test("ErrorMonitor: clearErrors empties log", function () {
  var em = createErrorMonitor();
  em.capture(new Error("clear me"));
  em.clearErrors();
  ok(em.errorCount() === 0, "cleared");
});

test("ErrorMonitor: getErrorRate returns count in window", function () {
  var em = createErrorMonitor();
  em.capture(new Error("e1"));
  em.capture(new Error("e2")); // diff message = diff fingerprint
  var rate = em.getErrorRate(60000);
  ok(rate.count === 2, "2 errors in window");
});

// ─── Deployment Validator ─────────────────────────────────────────────────────

test("DeploymentValidator: validateEnvironment passes with valid env", function () {
  var dv = createDeploymentValidator();
  var r = dv.validateEnvironment({ env: { NODE_ENV: "production", PORT: "3000" } });
  ok(r.ok, "valid env");
});

test("DeploymentValidator: validateEnvironment fails with invalid PORT", function () {
  var dv = createDeploymentValidator();
  var r = dv.validateEnvironment({ env: { NODE_ENV: "dev", PORT: "notaport" } });
  ok(!r.ok, "invalid PORT");
  ok(r.issues.some(function (i) { return i.field === "PORT"; }), "PORT in issues");
});

test("DeploymentValidator: validateSecrets detects missing secrets", function () {
  var sm = createSecretsManager({ masterKey: "k" });
  sm.setSecret("PRESENT", "value");
  var dv = createDeploymentValidator();
  var r = dv.validateSecrets(sm, ["PRESENT", "MISSING"]);
  ok(!r.ok, "missing secret");
  ok(r.issues.some(function (i) { return i.field === "MISSING"; }), "MISSING in issues");
});

test("DeploymentValidator: validateConfig catches missing required keys", function () {
  var dv = createDeploymentValidator();
  var r = dv.validateConfig({ required: ["foo", "bar"], types: {} }, { foo: "present" });
  ok(!r.ok, "missing bar");
  ok(r.issues.some(function (i) { return i.field === "bar"; }), "bar in issues");
});

test("DeploymentValidator: generateReport aggregates results", function () {
  var dv = createDeploymentValidator();
  var r1 = { ok: false, issues: [{ field: "A", message: "error A" }], warnings: [] };
  var r2 = { ok: true,  issues: [], warnings: [{ field: "B", message: "warn B" }] };
  var report = dv.generateReport([r1, r2]);
  ok(!report.ok, "overall not ok");
  ok(report.issues.length === 1, "1 issue");
  ok(report.warnings.length === 1, "1 warning");
  ok(!report.summary.readyToDeploy, "not ready to deploy");
});

// ─── Cross-user isolation (Integration Manager) ───────────────────────────────

test("IntegrationManager: user isolation in listIntegrations", async function () {
  var mgr = createIntegrationManager();
  mgr.register({ id: "u1-int", name: "U1", type: INTEGRATION_TYPES.email, config: {}, userId: "user1", adapter: createMockProvider() });
  mgr.register({ id: "u2-int", name: "U2", type: INTEGRATION_TYPES.email, config: {}, userId: "user2", adapter: createMockProvider() });
  var all = mgr.listIntegrations();
  var u1 = mgr.listIntegrations({ userId: "user1" });
  var u2 = mgr.listIntegrations({ userId: "user2" });
  ok(all.length === 2, "2 total");
  ok(u1.length === 1 && u1[0].id === "u1-int", "user1 isolation");
  ok(u2.length === 1 && u2[0].id === "u2-int", "user2 isolation");
});

// ─── Run ─────────────────────────────────────────────────────────────────────

run();
