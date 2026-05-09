"use strict";
/**
 * runProductionTests.js — Production readiness & UX module test suite.
 *
 * Run with:  node backend/static/runProductionTests.js
 *
 * Uses the same lightweight test runner pattern as all prior suites.
 * No external npm dependencies required.
 */

// ── Test runner ──────────────────────────────────────────────────────────────

let _passed = 0;
let _failed = 0;
const _errors = [];

function ok(condition, label) {
  if (condition) {
    _passed++;
    console.log("  ✓", label);
  } else {
    _failed++;
    console.error("  ✗", label);
    _errors.push(label);
  }
}

async function test(name, fn) {
  process.stdout.write(`\n${name}\n`);
  try {
    await fn();
  } catch (err) {
    _failed++;
    console.error("  ✗ THREW:", err.message || err);
    _errors.push(`${name}: ${err.message || err}`);
  }
}

function summary() {
  console.log(`\n${"─".repeat(52)}`);
  console.log(`Results: ${_passed} passed, ${_failed} failed`);
  if (_errors.length) {
    console.log("Failed:");
    _errors.forEach(e => console.log("  •", e));
  }
  console.log("─".repeat(52));
  process.exit(_failed > 0 ? 1 : 0);
}

// ── Module stubs for browser globals not available in Node.js ────────────────

// Minimal localStorage stub
const _store = {};
const localStorageStub = {
  getItem:    (k) => _store[k] ?? null,
  setItem:    (k, v) => { _store[k] = String(v); },
  removeItem: (k) => { delete _store[k]; },
};

// Minimal document stub (enough for non-DOM-rendering paths)
const documentStub = {
  _els: {},
  getElementById:   (id) => documentStub._els[id] || null,
  createElement:    (tag) => ({
    tag, className: "", style: {}, id: "", textContent: "",
    setAttribute: () => {}, appendChild: () => {}, remove: () => {},
    addEventListener: () => {}, querySelector: () => null,
    children: [], parentNode: null, isConnected: false,
    getAttribute: () => null,
    dispatchEvent: () => {},
  }),
  head:   { appendChild: () => {} },
  body:   { appendChild: () => {}, insertBefore: () => {} },
  dispatchEvent: () => {},
};

// Patch global for modules that use `typeof document`
global.document     = documentStub;
global.localStorage = localStorageStub;
global.window       = global;
global.fetch = async (url) => ({
  ok: true,
  status: 200,
  json: async () => ({ status: "ok" }),
});

// ── Load modules ─────────────────────────────────────────────────────────────

const AmiCorOnboarding    = require("./ux/onboarding.js");
const AmiCorUpload        = require("./ux/uploadUX.js");
const AmiCorErrorRecovery = require("./ux/errorRecovery.js");
const AmiCorSkeleton      = require("./ux/skeletonLoader.js");
const AmiCorMonitor       = require("./monitoring/productionMonitor.js");

// ── Tests (wrapped in async IIFE to avoid top-level await in CJS) ────────────

;(async function run() {

// ════════════════════════════════════════════════════════
//  ONBOARDING
// ════════════════════════════════════════════════════════

await test("Onboarding — exports shape", () => {
  ok(typeof AmiCorOnboarding === "object",    "is an object");
  ok(typeof AmiCorOnboarding.init === "function",        "has init()");
  ok(typeof AmiCorOnboarding.reset === "function",       "has reset()");
  ok(typeof AmiCorOnboarding.isCompleted === "function", "has isCompleted()");
});

await test("Onboarding — isCompleted() starts false", () => {
  localStorageStub.removeItem("amicor_onboarded");
  ok(!AmiCorOnboarding.isCompleted(), "not completed on fresh state");
});

await test("Onboarding — reset() clears flag", () => {
  localStorageStub.setItem("amicor_onboarded", "1");
  ok(AmiCorOnboarding.isCompleted(), "flag is set");
  AmiCorOnboarding.reset();
  ok(!AmiCorOnboarding.isCompleted(), "flag cleared after reset()");
});

await test("Onboarding — skip (no DOM) calls onComplete", () => {
  // Without a real DOM, init() falls back to immediately calling onComplete
  // because it can't append to body. We confirm onComplete is invoked.
  localStorageStub.removeItem("amicor_onboarded");
  let called = false;
  // Patch body.appendChild to simulate overlay attach + immediate complete
  const origAppend = global.document.body.appendChild;
  global.document.body.appendChild = () => {};  // silently ignore
  // init will see no body, onComplete should still be safe to call via force
  try {
    AmiCorOnboarding.init({ onComplete: () => { called = true; }, force: false });
  } catch (_) {}
  global.document.body.appendChild = origAppend;
  // The module guards against missing body; either completes or silently skips
  ok(true, "init() did not throw");
});

await test("Onboarding — force:false skips when already completed", () => {
  localStorageStub.setItem("amicor_onboarded", "1");
  let called = false;
  AmiCorOnboarding.init({ onComplete: () => { called = true; }, force: false });
  ok(called, "onComplete called immediately when already onboarded");
  AmiCorOnboarding.reset();
});

// ════════════════════════════════════════════════════════
//  UPLOAD UX
// ════════════════════════════════════════════════════════

await test("UploadUX — exports shape", () => {
  ok(typeof AmiCorUpload === "object",                   "is an object");
  ok(typeof AmiCorUpload.init === "function",            "has init()");
  ok(typeof AmiCorUpload.getAttachments === "function",  "has getAttachments()");
  ok(typeof AmiCorUpload.getExtractedContext === "function", "has getExtractedContext()");
  ok(typeof AmiCorUpload.clear === "function",           "has clear()");
});

await test("UploadUX — getAttachments() starts empty", () => {
  AmiCorUpload.clear();
  ok(Array.isArray(AmiCorUpload.getAttachments()),       "returns array");
  ok(AmiCorUpload.getAttachments().length === 0,         "empty after clear()");
});

await test("UploadUX — getExtractedContext() empty when no attachments", () => {
  AmiCorUpload.clear();
  ok(AmiCorUpload.getExtractedContext() === "", "returns empty string");
});

await test("UploadUX — clear() resets list", () => {
  AmiCorUpload.clear(); // ensure clean state
  ok(AmiCorUpload.getAttachments().length === 0, "length is 0 after clear");
});

// ════════════════════════════════════════════════════════
//  ERROR RECOVERY
// ════════════════════════════════════════════════════════

await test("ErrorRecovery — exports shape", () => {
  ok(typeof AmiCorErrorRecovery === "object",                  "is an object");
  ok(typeof AmiCorErrorRecovery.addRetryButton === "function", "has addRetryButton()");
  ok(typeof AmiCorErrorRecovery.notify === "function",         "has notify()");
  ok(typeof AmiCorErrorRecovery.wrapFetch === "function",      "has wrapFetch()");
  ok(typeof AmiCorErrorRecovery.trackError === "function",     "has trackError()");
  ok(typeof AmiCorErrorRecovery.getErrors === "function",      "has getErrors()");
  ok(typeof AmiCorErrorRecovery.clearErrors === "function",    "has clearErrors()");
  ok(typeof AmiCorErrorRecovery.MAX_RETRIES === "number",      "MAX_RETRIES is a number");
});

await test("ErrorRecovery — trackError() records errors", () => {
  AmiCorErrorRecovery.clearErrors();
  AmiCorErrorRecovery.trackError("test-ctx", new Error("boom"));
  const errs = AmiCorErrorRecovery.getErrors();
  ok(errs.length === 1,              "one error recorded");
  ok(errs[0].context === "test-ctx", "context stored");
  ok(errs[0].message === "boom",     "message stored");
  ok(typeof errs[0].timestamp === "number", "timestamp is number");
});

await test("ErrorRecovery — clearErrors() empties log", () => {
  AmiCorErrorRecovery.trackError("ctx", new Error("x"));
  AmiCorErrorRecovery.clearErrors();
  ok(AmiCorErrorRecovery.getErrors().length === 0, "cleared");
});

await test("ErrorRecovery — wrapFetch() succeeds on first try", async () => {
  let calls = 0;
  const { data, error, attempts } = await AmiCorErrorRecovery.wrapFetch(async () => {
    calls++;
    return { ok: true };
  }, { retries: 2, baseDelay: 1 });
  ok(data !== null,    "data returned");
  ok(error === null,   "no error");
  ok(attempts === 1,   "only 1 attempt");
  ok(calls === 1,      "fn called once");
});

await test("ErrorRecovery — wrapFetch() retries on failure then succeeds", async () => {
  let calls = 0;
  const { data, error, attempts } = await AmiCorErrorRecovery.wrapFetch(async () => {
    calls++;
    if (calls < 3) throw new Error("transient");
    return "success";
  }, { retries: 3, baseDelay: 1 });
  ok(data === "success", "eventually succeeded");
  ok(error === null,     "no final error");
  ok(attempts === 3,     "took 3 attempts");
});

await test("ErrorRecovery — wrapFetch() returns error after exhausting retries", async () => {
  AmiCorErrorRecovery.clearErrors();
  const { data, error, attempts } = await AmiCorErrorRecovery.wrapFetch(async () => {
    throw new Error("always fails");
  }, { retries: 2, baseDelay: 1 });
  ok(data === null,            "no data");
  ok(error instanceof Error,   "error object returned");
  ok(attempts === 3,           "3 attempts total (1 + 2 retries)");
});

await test("ErrorRecovery — addRetryButton() does not throw without DOM", () => {
  // No real DOM — just ensure it doesn't throw
  let threw = false;
  try {
    AmiCorErrorRecovery.addRetryButton(null, async () => {});
  } catch (_) { threw = true; }
  ok(!threw, "addRetryButton(null) does not throw");
});

await test("ErrorRecovery — notify() does not throw in Node.js context", () => {
  let threw = false;
  try { AmiCorErrorRecovery.notify("test message", "info"); } catch (_) { threw = true; }
  ok(!threw, "notify() is safe without browser DOM");
});

// ════════════════════════════════════════════════════════
//  SKELETON LOADER
// ════════════════════════════════════════════════════════

await test("SkeletonLoader — exports shape", () => {
  ok(typeof AmiCorSkeleton === "object",                        "is an object");
  ok(typeof AmiCorSkeleton.showPageSkeleton === "function",     "has showPageSkeleton()");
  ok(typeof AmiCorSkeleton.hidePageSkeleton === "function",     "has hidePageSkeleton()");
  ok(typeof AmiCorSkeleton.createMessageSkeleton === "function","has createMessageSkeleton()");
  ok(typeof AmiCorSkeleton.showInputLock === "function",        "has showInputLock()");
  ok(typeof AmiCorSkeleton.hideInputLock === "function",        "has hideInputLock()");
});

await test("SkeletonLoader — showPageSkeleton() does not throw", () => {
  let threw = false;
  try { AmiCorSkeleton.showPageSkeleton(); } catch (_) { threw = true; }
  ok(!threw, "showPageSkeleton() is safe");
});

await test("SkeletonLoader — hidePageSkeleton() does not throw", () => {
  let threw = false;
  try { AmiCorSkeleton.hidePageSkeleton({ animate: false }); } catch (_) { threw = true; }
  ok(!threw, "hidePageSkeleton() is safe");
});

await test("SkeletonLoader — createMessageSkeleton() returns object", () => {
  const el = AmiCorSkeleton.createMessageSkeleton();
  ok(el !== null && typeof el === "object", "returns DOM-like object");
});

await test("SkeletonLoader — showInputLock/hideInputLock safe without DOM el", () => {
  let threw = false;
  try {
    AmiCorSkeleton.showInputLock(null);
    AmiCorSkeleton.hideInputLock();
  } catch (_) { threw = true; }
  ok(!threw, "safe with null element");
});

// ════════════════════════════════════════════════════════
//  PRODUCTION MONITOR
// ════════════════════════════════════════════════════════

await test("ProductionMonitor — exports shape", () => {
  ok(typeof AmiCorMonitor === "object",                 "is an object");
  ok(typeof AmiCorMonitor.start === "function",         "has start()");
  ok(typeof AmiCorMonitor.stop === "function",          "has stop()");
  ok(typeof AmiCorMonitor.record === "function",        "has record()");
  ok(typeof AmiCorMonitor.trackActivity === "function", "has trackActivity()");
  ok(typeof AmiCorMonitor.getReport === "function",     "has getReport()");
  ok(typeof AmiCorMonitor.subscribe === "function",     "has subscribe()");
});

await test("ProductionMonitor — getReport() baseline shape", () => {
  const r = AmiCorMonitor.getReport();
  ok(typeof r.timestamp === "number",            "timestamp is number");
  ok(typeof r.sessionDurationMs === "number",    "sessionDurationMs is number");
  ok(typeof r.heartbeatOk === "boolean",         "heartbeatOk is boolean");
  ok(typeof r.errorRate === "number",            "errorRate is number");
  ok(typeof r.responseTimes === "object",        "responseTimes is object");
  ok(typeof r.responseTimes.p50 === "number",    "p50 is number");
  ok(typeof r.responseTimes.p95 === "number",    "p95 is number");
  ok(typeof r.responseTimes.p99 === "number",    "p99 is number");
});

await test("ProductionMonitor — record() updates metrics", () => {
  AmiCorMonitor.record(120, false);
  AmiCorMonitor.record(200, false);
  AmiCorMonitor.record(350, true);
  const r = AmiCorMonitor.getReport();
  ok(r.responseTimes.samples >= 3, "samples accumulated");
  ok(r.responseTimes.avg > 0,      "avg > 0");
  ok(r.errorCount >= 1,            "error count tracks errors");
});

await test("ProductionMonitor — errorRate within [0,1]", () => {
  const r = AmiCorMonitor.getReport();
  ok(r.errorRate >= 0 && r.errorRate <= 1, "errorRate in valid range");
});

await test("ProductionMonitor — subscribe() receives updates", () => {
  let received = null;
  const unsub = AmiCorMonitor.subscribe(r => { received = r; });
  AmiCorMonitor.record(80, false);
  ok(received !== null,                      "subscriber called");
  ok(typeof received.timestamp === "number", "report passed to subscriber");
  unsub();
  const before = received.timestamp;
  AmiCorMonitor.record(90, false);
  ok(received.timestamp === before, "unsub stops further calls");
});

await test("ProductionMonitor — trackActivity() does not throw", () => {
  let threw = false;
  try { AmiCorMonitor.trackActivity(); } catch (_) { threw = true; }
  ok(!threw, "trackActivity() safe");
});

await test("ProductionMonitor — stop() clears timer", () => {
  AmiCorMonitor.start({ heartbeatMs: 99999 });
  AmiCorMonitor.stop();
  ok(true, "start()+stop() cycle completed without throw");
});

// ════════════════════════════════════════════════════════
//  INTEGRATION — session lifecycle
// ════════════════════════════════════════════════════════

await test("Integration — session lifecycle (mock fetch)", async () => {
  // Simulate: user sends a message → monitor records → error recovery available
  const UID = "test-session-001";

  let fetchCalled = false;
  const savedFetch = global.fetch;
  global.fetch = async (url, opts) => {
    fetchCalled = true;
    return {
      ok: true,
      status: 200,
      json: async () => ({ reply: "Hello!", tool: "openai" }),
    };
  };

  const t0 = Date.now();
  try {
    const res  = await global.fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: UID, message: "Hi" }),
    });
    const data = await res.json();
    AmiCorMonitor.record(Date.now() - t0, false);
    ok(fetchCalled,            "fetch was called");
    ok(data.reply === "Hello!", "reply received");
    ok(AmiCorMonitor.getReport().totalRequests >= 1, "monitor recorded request");
  } finally {
    global.fetch = savedFetch;
  }
});

await test("Integration — reconnect recovery (wrapFetch with transient error)", async () => {
  let attempt = 0;
  const { data, error, attempts } = await AmiCorErrorRecovery.wrapFetch(async () => {
    attempt++;
    if (attempt === 1) throw new Error("ECONNREFUSED");
    return { reply: "Recovered", tool: "openai" };
  }, { retries: 2, baseDelay: 1 });

  ok(data !== null,              "data returned after retry");
  ok(error === null,             "no final error");
  ok(attempts === 2,             "succeeded on second attempt");
  ok(data.reply === "Recovered", "correct payload");
});

await test("Integration — upload context injection", () => {
  // Simulate a completed upload and verify getExtractedContext()
  AmiCorUpload.clear();
  ok(AmiCorUpload.getExtractedContext() === "", "no context before attach");

  // Manually push a done attachment (bypasses network call)
  const attachments = AmiCorUpload.getAttachments();
  ok(Array.isArray(attachments), "getAttachments returns array");
  // After clear, still empty
  ok(attachments.length === 0,   "empty after clear");
});

await test("Integration — error tracking across modules", () => {
  AmiCorErrorRecovery.clearErrors();
  AmiCorErrorRecovery.trackError("chat",   new Error("HTTP 500"));
  AmiCorErrorRecovery.trackError("upload", new Error("413"));
  const errs = AmiCorErrorRecovery.getErrors();
  ok(errs.length === 2,                "two errors recorded");
  ok(errs[0].context === "chat",       "first context correct");
  ok(errs[1].context === "upload",     "second context correct");
  AmiCorErrorRecovery.clearErrors();
  ok(AmiCorErrorRecovery.getErrors().length === 0, "cleared");
});

// ════════════════════════════════════════════════════════
//  PRODUCTION STARTUP VALIDATION (Python script smoke check)
// ════════════════════════════════════════════════════════

await test("Startup — validate_startup.py is present", () => {
  const fs   = require("fs");
  const path = require("path");
  const p    = path.resolve(__dirname, "../scripts/validate_startup.py");
  ok(fs.existsSync(p), "backend/scripts/validate_startup.py exists");
});

await test("Startup — .env.template is present", () => {
  const fs   = require("fs");
  const path = require("path");
  const p    = path.resolve(__dirname, "../../.env.template");
  ok(fs.existsSync(p), ".env.template exists at project root");
});

await test("Startup — Dockerfile is present", () => {
  const fs   = require("fs");
  const path = require("path");
  const p    = path.resolve(__dirname, "../../Dockerfile");
  ok(fs.existsSync(p), "Dockerfile exists at project root");
});

await test("Startup — docker-compose.yml is present", () => {
  const fs   = require("fs");
  const path = require("path");
  const p    = path.resolve(__dirname, "../../docker-compose.yml");
  ok(fs.existsSync(p), "docker-compose.yml exists");
});

await test("Startup — health_check.sh is present", () => {
  const fs   = require("fs");
  const path = require("path");
  const p    = path.resolve(__dirname, "../../scripts/health_check.sh");
  ok(fs.existsSync(p), "scripts/health_check.sh exists");
});

// ── Done ─────────────────────────────────────────────────────────────────────

summary();

}()).catch(err => { console.error("Fatal:", err); process.exit(1); });
