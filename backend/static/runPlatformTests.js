#!/usr/bin/env node
// runPlatformTests.js — npm run test:platform
// Tests the new platform layer: DB, auth, admin endpoints.
// Requires backend running at http://127.0.0.1:8000

const BASE = process.env.API_URL || "http://127.0.0.1:8000";

let pass = 0, fail = 0;
const errors = [];

function ok(name, cond, detail = "") {
  if (cond) { console.log(`  PASS  ${name}`); pass++; }
  else       { console.error(`  FAIL  ${name}${detail ? " — " + detail : ""}`); fail++; errors.push(name); }
}

async function req(method, path, body, headers = {}) {
  const opts = { method, headers: { "Content-Type": "application/json", ...headers } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  let data;
  try { data = await res.json(); } catch { data = null; }
  return { status: res.status, data, headers: res.headers };
}

// ── Unique test user ──────────────────────────────────────────────────────────
const stamp    = Date.now();
const email    = `test_${stamp}@platform.test`;
const password = `Amicor$test${stamp}`;
let accessToken = null;
let refreshToken = null;

async function tests() {
  console.log(`\n=== Platform Tests  (${BASE}) ===\n`);

  // ── 1. Admin dashboard reachable ──────────────────────────────────────────
  console.log("── Admin ────────────────────────────────");
  {
    const r = await req("GET", "/api/admin/dashboard");
    ok("GET /api/admin/dashboard → 200",   r.status === 200);
    ok("dashboard.status = ok",            r.data?.status === "ok");
    ok("dashboard.database.reachable",     r.data?.database?.reachable === true);
    ok("dashboard has platform.registered_users", typeof r.data?.platform?.registered_users === "number");
    ok("dashboard has observability block", r.data?.observability != null);
  }

  // ── 2. Metrics endpoint ───────────────────────────────────────────────────
  {
    const r = await req("GET", "/api/admin/metrics");
    ok("GET /api/admin/metrics → 200",  r.status === 200);
    ok("metrics has uptime_seconds",    typeof r.data?.uptime_seconds === "number");
    ok("metrics has counters",          r.data?.counters != null);
  }

  // ── 3. Register ───────────────────────────────────────────────────────────
  console.log("\n── Auth: Register ──────────────────────");
  {
    const r = await req("POST", "/api/auth/register", { email, password, display_name: "Test Platform" });
    ok("POST /api/auth/register → 201",  r.status === 201);
    ok("register returns user_id",       typeof r.data?.user_id === "string");
    ok("register returns email",         r.data?.email === email);
  }

  // Duplicate email → 409
  {
    const r = await req("POST", "/api/auth/register", { email, password });
    ok("Duplicate register → 409",       r.status === 409);
  }

  // ── 4. Login ──────────────────────────────────────────────────────────────
  console.log("\n── Auth: Login ─────────────────────────");
  {
    const r = await req("POST", "/api/auth/login", { email, password });
    ok("POST /api/auth/login → 200",     r.status === 200);
    ok("login returns access_token",     typeof r.data?.access_token === "string");
    ok("login returns refresh_token",    typeof r.data?.refresh_token === "string");
    ok("login returns email",            r.data?.email === email);
    accessToken  = r.data?.access_token;
    refreshToken = r.data?.refresh_token;
  }

  // Wrong password → 401
  {
    const r = await req("POST", "/api/auth/login", { email, password: "wrong" });
    ok("Wrong password → 401",           r.status === 401);
  }

  // ── 5. /api/auth/me ───────────────────────────────────────────────────────
  console.log("\n── Auth: Me ────────────────────────────");
  {
    const r = await req("GET", "/api/auth/me", null, { Authorization: `Bearer ${accessToken}` });
    ok("GET /api/auth/me → 200",         r.status === 200);
    ok("/me returns email",              r.data?.email === email);
    ok("/me returns display_name",       typeof r.data?.display_name === "string");
  }

  // No token → 401
  {
    const r = await req("GET", "/api/auth/me");
    ok("/api/auth/me without token → 401", r.status === 401);
  }

  // ── 6. Refresh ────────────────────────────────────────────────────────────
  console.log("\n── Auth: Refresh ───────────────────────");
  {
    const r = await req("POST", "/api/auth/refresh", { refresh_token: refreshToken });
    ok("POST /api/auth/refresh → 200",   r.status === 200);
    ok("refresh returns new access_token", typeof r.data?.access_token === "string");
  }

  // ── 7. Logout ─────────────────────────────────────────────────────────────
  console.log("\n── Auth: Logout ────────────────────────");
  {
    const r = await req("POST", "/api/auth/logout", { refresh_token: refreshToken },
                        { Authorization: `Bearer ${accessToken}` });
    ok("POST /api/auth/logout → 200",    r.status === 200);
  }

  // Revoked refresh token → 401
  {
    const r = await req("POST", "/api/auth/refresh", { refresh_token: refreshToken });
    ok("Revoked refresh → 401",          r.status === 401);
  }

  // ── 8. Admin dashboard updated user count ────────────────────────────────
  console.log("\n── Admin: Post-registration count ──────");
  {
    const r = await req("GET", "/api/admin/dashboard");
    ok("registered_users ≥ 1 after register", (r.data?.platform?.registered_users ?? 0) >= 1);
  }

  // ── Summary ───────────────────────────────────────────────────────────────
  console.log(`\n${"─".repeat(46)}`);
  console.log(`Platform tests: ${pass} PASS  ${fail} FAIL`);
  if (errors.length) console.error("Failed:", errors.join(", "));
  process.exitCode = fail > 0 ? 1 : 0;
}

tests().catch(e => { console.error("Fatal:", e.message); process.exitCode = 1; });
