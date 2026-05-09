#!/usr/bin/env node
// runDatabaseTests.js — npm run test:database
// Tests SQLite legacy DB + SQLAlchemy platform DB persistence.

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
  return { status: res.status, data };
}

async function tests() {
  console.log(`\n=== Database Tests  (${BASE}) ===\n`);

  // ── 1. Legacy DB reachable (via /api/health) ──────────────────────────────
  console.log("── Legacy DB (SQLite) ──────────────────");
  {
    const r = await req("GET", "/api/health");
    ok("GET /api/health → 200",          r.status === 200);
    ok("health.database reachable",      r.data?.database?.reachable === true || r.data?.status === "ok");
  }

  // ── 2. Message persistence ────────────────────────────────────────────────
  console.log("\n── Message persistence ─────────────────");
  const uid  = `db_test_${Date.now()}`;
  const msg1 = `Hello DB test ${Date.now()}`;

  // Send a chat message
  {
    const r = await req("POST", "/api/chat", { message: msg1, user_id: uid });
    ok("POST /api/chat → 200",           r.status === 200);
    ok("chat returns reply",             typeof r.data?.reply === "string" && r.data.reply.length > 0);
  }

  // History should contain the sent message
  {
    const r = await req("GET", `/api/history/${uid}?limit=20`);
    ok("GET /api/history/{user_id} → 200", r.status === 200);
    const messages = Array.isArray(r.data?.messages) ? r.data.messages : null;
    ok("history.messages is array",      Array.isArray(messages));
    const found = Array.isArray(messages) && messages.some(m =>
      (m.content || m.message || "").includes(msg1.slice(0, 20))
    );
    ok("sent message in history",        found, "message not found in history");
  }

  // ── 3. Platform DB reachable (via admin dashboard) ────────────────────────
  console.log("\n── Platform DB (SQLAlchemy) ────────────");
  {
    const r = await req("GET", "/api/admin/dashboard");
    ok("GET /api/admin/dashboard → 200",  r.status === 200);
    ok("platform_db.reachable = true",    r.data?.database?.reachable === true);
  }

  // ── 4. Platform user persists across requests ──────────────────────────────
  console.log("\n── Platform user persistence ───────────");
  const email    = `persist_${Date.now()}@db.test`;
  const password = `Persist!${Date.now()}`;
  let token = null;

  {
    await req("POST", "/api/auth/register", { email, password });
    const r = await req("POST", "/api/auth/login", { email, password });
    ok("Login after register → 200",     r.status === 200);
    token = r.data?.access_token;
  }

  {
    const r = await req("GET", "/api/auth/me", null, { Authorization: `Bearer ${token}` });
    ok("/me returns correct email",      r.data?.email === email);
  }

  // Second login (simulates server restart — same DB)
  {
    const r = await req("POST", "/api/auth/login", { email, password });
    ok("Second login (same session) → 200", r.status === 200);
    ok("Same email returned",            r.data?.email === email);
  }

  // ── 5. Upload counter increments ──────────────────────────────────────────
  console.log("\n── Upload counter ──────────────────────");
  {
    const r1 = await req("GET", "/api/admin/dashboard");
    const before = r1.data?.platform?.total_uploads ?? 0;

    // Upload a tiny text file
    const form = new FormData();
    form.append("file", new Blob(["hello world"], { type: "text/plain" }), "test.txt");
    const up = await fetch(`${BASE}/api/upload`, { method: "POST", body: form });
    ok("Upload text file → 200",         up.status === 200);

    const r2 = await req("GET", "/api/admin/dashboard");
    const after = r2.data?.platform?.total_uploads ?? 0;
    ok("Upload count incremented",       after > before, `before=${before} after=${after}`);
  }

  // ── Summary ───────────────────────────────────────────────────────────────
  console.log(`\n${"─".repeat(46)}`);
  console.log(`Database tests: ${pass} PASS  ${fail} FAIL`);
  if (errors.length) console.error("Failed:", errors.join(", "));
  process.exitCode = fail > 0 ? 1 : 0;
}

tests().catch(e => { console.error("Fatal:", e.message); process.exitCode = 1; });
