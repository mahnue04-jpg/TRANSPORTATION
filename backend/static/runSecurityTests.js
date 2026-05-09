#!/usr/bin/env node
// runSecurityTests.js — npm run test:security
// Tests: security headers, request tracing, rate limiting, input validation.

const BASE = process.env.API_URL || "http://127.0.0.1:8000";

let pass = 0, fail = 0;
const errors = [];

function ok(name, cond, detail = "") {
  if (cond) { console.log(`  PASS  ${name}`); pass++; }
  else       { console.error(`  FAIL  ${name}${detail ? " — " + detail : ""}`); fail++; errors.push(name); }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function req(method, path, body, headers = {}) {
  const opts = { method, headers: { "Content-Type": "application/json", ...headers } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  let data;
  try { data = await res.json(); } catch { data = null; }
  return { status: res.status, data, headers: res.headers };
}

async function tests() {
  console.log(`\n=== Security Tests  (${BASE}) ===\n`);

  // ── 1. Security headers ────────────────────────────────────────────────────
  console.log("── Security headers ────────────────────");
  {
    const r = await req("GET", "/api/health");
    const h = r.headers;
    ok("X-Content-Type-Options: nosniff",   h.get("x-content-type-options") === "nosniff");
    ok("X-Frame-Options: DENY",             h.get("x-frame-options") === "DENY");
    ok("X-XSS-Protection present",          !!h.get("x-xss-protection"));
    ok("Referrer-Policy present",           !!h.get("referrer-policy"));
    ok("Permissions-Policy present",        !!h.get("permissions-policy"));
    ok("Content-Security-Policy present",   !!h.get("content-security-policy"));
  }

  // ── 2. Request tracing header ──────────────────────────────────────────────
  console.log("\n── Request tracing ─────────────────────");
  {
    const r = await req("GET", "/api/health");
    ok("X-Request-ID header present",       !!r.headers.get("x-request-id"), r.headers.get("x-request-id"));
  }

  // Custom X-Request-ID is echoed back
  {
    const r = await req("GET", "/api/health", null, { "X-Request-ID": "my-custom-id-123" });
    ok("Custom X-Request-ID echoed",        r.headers.get("x-request-id") === "my-custom-id-123");
  }

  // ── 3. Auth endpoints require valid body ───────────────────────────────────
  console.log("\n── Input validation ────────────────────");
  {
    // Missing required fields → 422
    const r = await req("POST", "/api/auth/register", { email: "no-password@test.com" });
    ok("Register without password → 422",   r.status === 422);
  }
  {
    const r = await req("POST", "/api/auth/login", { email: "x" });
    ok("Login without password → 422",      r.status === 422);
  }
  {
    // Invalid email format → 422
    const r = await req("POST", "/api/auth/register", { email: "not-an-email", password: "abc123!" });
    ok("Invalid email format → 422",        r.status === 422);
  }

  // ── 4. Bearer auth — invalid token rejected ────────────────────────────────
  console.log("\n── Auth enforcement ────────────────────");
  {
    const r = await req("GET", "/api/auth/me", null, { Authorization: "Bearer garbage.token.here" });
    ok("Invalid JWT → 401",                 r.status === 401);
  }
  {
    const r = await req("GET", "/api/auth/me", null, { Authorization: "Bearer " });
    ok("Empty bearer → 401",               r.status === 401);
  }
  {
    const r = await req("GET", "/api/auth/me");
    ok("No auth header → 401",             r.status === 401);
  }

  // ── 5. Upload size limit ───────────────────────────────────────────────────
  console.log("\n── Upload limits ───────────────────────");
  {
    // 11 MB text/plain blob — exceeds 10 MB limit and should hit size guard (413).
    const big = new Blob([new Uint8Array(11 * 1024 * 1024)], { type: "text/plain" });
    const form = new FormData();
    form.append("file", big, "huge.txt");
    const res = await fetch(`${BASE}/api/upload`, { method: "POST", body: form });
    ok("11 MB upload → 413",              res.status === 413, `got ${res.status}`);
  }

  // ── 6. CORS — disallowed origin ───────────────────────────────────────────
  console.log("\n── CORS ────────────────────────────────");
  {
    const res = await fetch(`${BASE}/api/health`, {
      headers: { Origin: "https://evil.example.com" },
    });
    const acao = res.headers.get("access-control-allow-origin");
    // Should not echo back the evil origin
    ok("Disallowed origin not reflected",  acao !== "https://evil.example.com",
      `ACAO: ${acao}`);
  }

  // ── 7. Rate limit probe (auth endpoint) ───────────────────────────────────
  // We send RATE_LIMIT_AUTH requests + a few extra; at least one should 429.
  // Skip if SKIP_RATE_LIMIT_TEST=1 (e.g. CI with shared IP concerns).
  if (!process.env.SKIP_RATE_LIMIT_TEST) {
    console.log("\n── Rate limiting ───────────────────────");
    const BURST = 30;   // send 30 rapid logins — default limit is 5/5min
    let got429 = false;
    for (let i = 0; i < BURST; i++) {
      const r = await req("POST", "/api/auth/login", {
        email: `ratelimit_${i}@test.invalid`, password: "x",
      });
      if (r.status === 429) { got429 = true; break; }
    }
    ok(`Rate limit triggers within ${BURST} auth requests`, got429,
      "no 429 observed — check RATE_LIMIT_AUTH env var");
  }

  // ── Summary ───────────────────────────────────────────────────────────────
  console.log(`\n${"─".repeat(46)}`);
  console.log(`Security tests: ${pass} PASS  ${fail} FAIL`);
  if (errors.length) console.error("Failed:", errors.join(", "));
  process.exitCode = fail > 0 ? 1 : 0;
}

tests().catch(e => { console.error("Fatal:", e.message); process.exitCode = 1; });
