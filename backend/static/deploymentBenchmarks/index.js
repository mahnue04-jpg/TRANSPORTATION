"use strict";

/**
 * deploymentBenchmarks/index.js — Benchmark collector and formatter for deployment layer.
 * Also the entry point: node backend/static/deploymentBenchmarks/index.js
 */

const path = require("path");
const base = path.join(__dirname, "..");

const {
  createIntegrationManager,
  createApiConnector,
  createWebhookSystem,
  createEmailProvider,
  createNotificationProvider,
  createMockProvider,
  INTEGRATION_TYPES,
  WEBHOOK_EVENTS,
} = require(path.join(base, "integrations/index"));

const {
  createEnvironmentConfig,
  createSecretsManager,
  createLogger,
  createTelemetry,
  createHealthMonitor,
  createRateLimiter,
  createErrorMonitor,
  LOG_LEVELS,
} = require(path.join(base, "deployment/index"));

// ─── Benchmark Infrastructure ─────────────────────────────────────────────────

function createBenchmarkCollector() {
  var results = [];

  async function runBatch(label, count, executor) {
    var times = [];
    var errors = 0;
    var start = process.hrtime.bigint();

    for (var i = 0; i < count; i++) {
      var t0 = process.hrtime.bigint();
      try { await executor(i); } catch (_) { errors++; }
      times.push(Number(process.hrtime.bigint() - t0) / 1e6); // ms
    }

    var totalMs = Number(process.hrtime.bigint() - start) / 1e6;
    var avg = times.reduce(function (a, b) { return a + b; }, 0) / times.length;
    var sorted = times.slice().sort(function (a, b) { return a - b; });
    var p50 = sorted[Math.floor(sorted.length * 0.50)];
    var p95 = sorted[Math.floor(sorted.length * 0.95)];
    var p99 = sorted[Math.floor(sorted.length * 0.99)];

    var result = { label, count, totalMs, avgMs: avg, p50, p95, p99, errors, opsPerSec: Math.round(count / (totalMs / 1000)) };
    results.push(result);
    return result;
  }

  function getResults() { return results.slice(); }

  return { runBatch, getResults };
}

function formatBenchmarkReport(results) {
  var lines = [
    "\n╔══════════════════════════════════════════════════════════════════════════╗",
    "║             Deployment + Integration Benchmark Report                    ║",
    "╚══════════════════════════════════════════════════════════════════════════╝",
    "",
    padRight("  Batch", 38) + padLeft("Ops", 8) + padLeft("Avg(ms)", 10) + padLeft("p50", 8) + padLeft("p95", 8) + padLeft("p99", 8) + padLeft("ops/s", 8) + padLeft("Err", 6),
    "  " + "─".repeat(84),
  ];

  results.forEach(function (r) {
    lines.push(
      padRight("  " + r.label, 38) +
      padLeft(r.count, 8) +
      padLeft(r.avgMs.toFixed(3), 10) +
      padLeft((r.p50 || 0).toFixed(2), 8) +
      padLeft((r.p95 || 0).toFixed(2), 8) +
      padLeft((r.p99 || 0).toFixed(2), 8) +
      padLeft(r.opsPerSec, 8) +
      padLeft(r.errors, 6)
    );
  });

  lines.push("\n  Total batches: " + results.length);
  lines.push("  Total errors:  " + results.reduce(function (s, r) { return s + r.errors; }, 0));
  lines.push("──────────────────────────────────────────────────────────────────────────\n");
  return lines.join("\n");
}

function padRight(s, len) { s = String(s); return s + " ".repeat(Math.max(0, len - s.length)); }
function padLeft(s, len) { s = String(s); return " ".repeat(Math.max(0, len - s.length)) + s; }

// ─── Setup shared fixtures ────────────────────────────────────────────────────

async function main() {
  var bc = createBenchmarkCollector();
  var REPS = 1000;

  // Integration registration
  await bc.runBatch("integration-registration", REPS, async function (i) {
    var mgr = createIntegrationManager();
    mgr.register({ id: "int-" + i, name: "Test", type: INTEGRATION_TYPES.email, config: {}, userId: "u1", adapter: createMockProvider() });
  });

  // API connector metrics read (circuit breaker closed path)
  var connector = createApiConnector({ defaultRetries: 0 });
  await bc.runBatch("api-connector-metrics", REPS, async function () {
    connector.getMetrics();
  });

  // Webhook dispatch (1 webhook, mock deliver)
  var ws = createWebhookSystem({
    deliver: async function () { return { ok: true }; },
  });
  ws.register({ integrationId: "bench-int", event: WEBHOOK_EVENTS.created });
  await bc.runBatch("webhook-dispatch", REPS, async function () {
    await ws.dispatch("bench-int", WEBHOOK_EVENTS.created, { data: "bench" });
  });

  // Email send (offline mock provider)
  var ep = createEmailProvider();
  await bc.runBatch("email-send", REPS, async function (i) {
    await ep.send({ to: "bench" + i + "@example.com", subject: "Test", text: "Body" });
  });

  // Notification send
  var np = createNotificationProvider();
  await bc.runBatch("notification-send", REPS, async function (i) {
    await np.send({ userId: "user" + (i % 10), title: "Bench", message: "msg" + i });
  });

  // Environment config lookup
  var cfg = createEnvironmentConfig({ env: { NODE_ENV: "production", API_URL: "https://api.example.com" } });
  await bc.runBatch("environment-config-get", REPS, function () {
    cfg.get("API_URL");
  });

  // Secrets get (decrypt round-trip)
  var sm = createSecretsManager({ masterKey: "benchmark-master-key-32bytes!!" });
  sm.setSecret("BENCH_SECRET", "my-benchmark-secret-value");
  await bc.runBatch("secrets-get", REPS, function () {
    sm.getSecret("BENCH_SECRET");
  });

  // Logger throughput (in-memory, no console)
  var logger = createLogger({ level: LOG_LEVELS.debug, transports: [] });
  await bc.runBatch("logger-write", REPS, function (i) {
    logger.info("bench message " + i, { context: { op: "bench" } });
  });

  // Telemetry spans
  var tel = createTelemetry();
  await bc.runBatch("telemetry-span", REPS, function (i) {
    var sid = tel.startSpan("bench.op." + (i % 5));
    tel.endSpan(sid);
  });

  // Health check all (all passing, 3 checks)
  var hm = createHealthMonitor({ defaultTimeoutMs: 100 });
  hm.registerCheck("c1", async function () { return { healthy: true }; });
  hm.registerCheck("c2", async function () { return { healthy: true }; });
  hm.registerCheck("c3", async function () { return { healthy: true }; });
  await bc.runBatch("health-check-all", Math.min(REPS, 200), async function () {
    await hm.runAll();
  });

  // Rate limiter check (not consume)
  var rl = createRateLimiter({ gcIntervalMs: 999999 });
  await bc.runBatch("rate-limiter-check", REPS, function (i) {
    rl.check("bench:user:" + (i % 100), { maxRequests: 100, windowMs: 60000 });
  });
  rl.destroy();

  // Error capture (mix of unique + deduped)
  var em = createErrorMonitor();
  await bc.runBatch("error-capture", REPS, function (i) {
    em.capture(new Error("bench error " + (i % 5)));
  });

  // Print report
  console.log(formatBenchmarkReport(bc.getResults()));
}

main().catch(function (err) { console.error("Benchmark failed:", err.message); process.exit(1); });
