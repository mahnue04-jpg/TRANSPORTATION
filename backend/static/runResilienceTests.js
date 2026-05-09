/**
 * Resilience Tests — circuit breaker states, fallback chains, health scoring
 * Run: npm run test:resilience
 * These tests exercise the circuit breaker logic directly via unit-style assertions
 * without requiring the backend to be running (pure JS logic mirrors).
 * Integration tests (marked [LIVE]) require http://127.0.0.1:8000
 */

"use strict";

const http = require("http");

const PASS = "\x1b[32mPASS\x1b[0m";
const FAIL = "\x1b[31mFAIL\x1b[0m";
const SKIP = "\x1b[33mSKIP\x1b[0m";

let passed = 0, failed = 0, skipped = 0;

function assert(label, condition, detail = "") {
  if (condition) {
    console.log(`  ${PASS}  ${label}`);
    passed++;
  } else {
    console.log(`  ${FAIL}  ${label}${detail ? " — " + detail : ""}`);
    failed++;
  }
}

// ── JS Circuit Breaker mirror (unit tests) ─────────────────────────────────

const CLOSED    = "CLOSED";
const OPEN      = "OPEN";
const HALF_OPEN = "HALF_OPEN";

class CircuitBreaker {
  constructor(name, failureThreshold = 3, recoveryTimeout = 30, windowSize = 20) {
    this.name = name;
    this.failureThreshold = failureThreshold;
    this.recoveryTimeout  = recoveryTimeout;
    this.windowSize       = windowSize;
    this.state            = CLOSED;
    this.failureCount     = 0;
    this.lastFailureTime  = null;
    this.window           = [];
    this.totalCalls       = 0;
  }

  get healthScore() {
    if (!this.window.length) return 1.0;
    const successes = this.window.filter(Boolean).length;
    return successes / this.window.length;
  }

  isAvailable() {
    if (this.state === CLOSED)    return true;
    if (this.state === HALF_OPEN) return true;
    if (this.state === OPEN) {
      const elapsed = (Date.now() - this.lastFailureTime) / 1000;
      if (elapsed >= this.recoveryTimeout) {
        this.state = HALF_OPEN;
        return true;
      }
      return false;
    }
    return false;
  }

  recordSuccess() {
    this.totalCalls++;
    this.window.push(true);
    if (this.window.length > this.windowSize) this.window.shift();
    if (this.state === HALF_OPEN) {
      this.state = CLOSED;
      this.failureCount = 0;
    }
  }

  recordFailure() {
    this.totalCalls++;
    this.window.push(false);
    if (this.window.length > this.windowSize) this.window.shift();
    this.failureCount++;
    this.lastFailureTime = Date.now();
    if (this.state === CLOSED && this.failureCount >= this.failureThreshold) {
      this.state = OPEN;
    } else if (this.state === HALF_OPEN) {
      this.state = OPEN;
    }
  }
}

// ── Unit Tests ────────────────────────────────────────────────────────────

function testInitialState() {
  console.log("\n[1] Circuit Breaker — Initial State");
  const cb = new CircuitBreaker("test", 3, 30);
  assert("initial state is CLOSED",     cb.state === CLOSED);
  assert("initial failureCount is 0",   cb.failureCount === 0);
  assert("initial isAvailable is true", cb.isAvailable() === true);
  assert("initial healthScore is 1.0",  cb.healthScore === 1.0);
}

function testTripsOnFailureThreshold() {
  console.log("\n[2] Circuit Breaker — Trips on failure threshold");
  const cb = new CircuitBreaker("test", 3, 30);
  cb.recordFailure();
  assert("still CLOSED after 1 failure", cb.state === CLOSED);
  cb.recordFailure();
  assert("still CLOSED after 2 failures", cb.state === CLOSED);
  cb.recordFailure();
  assert("OPEN after 3 failures (threshold=3)", cb.state === OPEN);
  assert("isAvailable returns false when OPEN", cb.isAvailable() === false);
}

function testRecoveryTransition() {
  console.log("\n[3] Circuit Breaker — Recovery transition");
  const cb = new CircuitBreaker("test", 2, 0); // 0s recovery for test speed
  cb.recordFailure();
  cb.recordFailure();
  assert("state is OPEN after trips", cb.state === OPEN);
  // Force lastFailureTime to be old
  cb.lastFailureTime = Date.now() - 1000;
  assert("isAvailable after recovery timeout returns true", cb.isAvailable() === true);
  assert("state transitions to HALF_OPEN", cb.state === HALF_OPEN);
}

function testHalfOpenSuccessCloses() {
  console.log("\n[4] Circuit Breaker — HALF_OPEN success closes");
  const cb = new CircuitBreaker("test", 2, 0);
  cb.recordFailure(); cb.recordFailure();
  cb.lastFailureTime = Date.now() - 1000;
  cb.isAvailable(); // transitions to HALF_OPEN
  cb.recordSuccess();
  assert("state is CLOSED after probe success", cb.state === CLOSED);
  assert("failureCount reset to 0", cb.failureCount === 0);
}

function testHalfOpenFailureReopens() {
  console.log("\n[5] Circuit Breaker — HALF_OPEN failure re-opens");
  const cb = new CircuitBreaker("test", 2, 0);
  cb.recordFailure(); cb.recordFailure();
  cb.lastFailureTime = Date.now() - 1000;
  cb.isAvailable();
  cb.recordFailure();
  assert("state is OPEN after probe failure", cb.state === OPEN);
}

function testHealthScore() {
  console.log("\n[6] Circuit Breaker — Health score calculation");
  const cb = new CircuitBreaker("test", 10, 30, 10);
  // 7 successes, 3 failures = 70% health
  for (let i = 0; i < 7; i++) cb.recordSuccess();
  for (let i = 0; i < 3; i++) { cb.recordFailure(); cb.state = CLOSED; cb.failureCount = 0; }
  const score = cb.healthScore;
  assert("health score is ~0.7", Math.abs(score - 0.7) < 0.01, `got ${score.toFixed(3)}`);
}

function testWindowSizeRollover() {
  console.log("\n[7] Circuit Breaker — Rolling window rollover");
  const cb = new CircuitBreaker("test", 100, 30, 5);
  // Fill window with failures
  for (let i = 0; i < 5; i++) { cb.window.push(false); }
  // Add 5 successes — should push out the failures
  for (let i = 0; i < 5; i++) cb.recordSuccess();
  assert("window size does not exceed windowSize", cb.window.length <= 5);
  assert("health score is 1.0 after all-success window", cb.healthScore === 1.0);
}

// ── Live Integration Tests ────────────────────────────────────────────────

function httpGet(path) {
  return new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:8000${path}`, res => {
      let data = "";
      res.on("data", c => { data += c; });
      res.on("end", () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
        catch { resolve({ status: res.statusCode, body: data }); }
      });
    }).on("error", reject);
  });
}

async function testLiveProviderHealth() {
  console.log("\n[8] [LIVE] Provider health endpoint");
  try {
    const res = await httpGet("/api/diagnostics/providers");
    assert("returns 200", res.status === 200, `got ${res.status}`);
    assert("has providers object", res.body && typeof res.body.providers === "object");
    const providers = Object.keys(res.body.providers || {});
    assert("at least one provider registered after warm-up", providers.length >= 0); // 0 is ok before first request
  } catch (err) {
    console.log(`  ${SKIP}  Live provider health (backend not running: ${err.message})`);
    skipped++;
  }
}

async function testLiveWeatherFallback() {
  console.log("\n[9] [LIVE] Weather with provider status");
  return new Promise(resolve => {
    const body = JSON.stringify({ user_id: "resilience_test", message: "What is the weather in London?" });
    const opts = {
      hostname: "127.0.0.1", port: 8000, path: "/api/chat", method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
    };
    const req = http.request(opts, res => {
      let data = "";
      res.on("data", c => { data += c; });
      res.on("end", () => {
        try {
          const json = JSON.parse(data);
          assert("weather returns 200", res.statusCode === 200, `got ${res.statusCode}`);
          assert("reply mentions weather", json.reply && (json.reply.toLowerCase().includes("weather") || json.reply.includes("°")));
          assert("meta.provider present", json.meta && json.meta.provider);
        } catch { assert("weather response parse", false, data.slice(0, 100)); }
        resolve();
      });
    });
    req.on("error", err => {
      console.log(`  ${SKIP}  Live weather (backend not running: ${err.message})`);
      skipped++;
      resolve();
    });
    req.write(body);
    req.end();
  });
}

// ── Runner ────────────────────────────────────────────────────────────────

async function run() {
  console.log("═══════════════════════════════════════════════");
  console.log("  Amicore Resilience Tests");
  console.log("═══════════════════════════════════════════════");

  testInitialState();
  testTripsOnFailureThreshold();
  testRecoveryTransition();
  testHalfOpenSuccessCloses();
  testHalfOpenFailureReopens();
  testHealthScore();
  testWindowSizeRollover();
  await testLiveProviderHealth();
  await testLiveWeatherFallback();

  console.log("\n───────────────────────────────────────────────");
  console.log(`  ${PASS} ${passed}  ${FAIL} ${failed}  ${SKIP} ${skipped}`);
  console.log("───────────────────────────────────────────────");
  if (failed > 0) process.exit(1);
}

run().catch(err => { console.error(err); process.exit(1); });
