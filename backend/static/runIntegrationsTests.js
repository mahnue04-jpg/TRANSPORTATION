#!/usr/bin/env node
// runIntegrationsTests.js — npm run test:integrations

const BASE = process.env.API_URL || "http://127.0.0.1:8000";

let pass = 0, fail = 0;
const errors = [];

function ok(name, cond, detail = "") {
  if (cond) { console.log(`  PASS  ${name}`); pass++; }
  else { console.error(`  FAIL  ${name}${detail ? " — " + detail : ""}`); fail++; errors.push(name); }
}

async function req(method, path, body, headers = {}) {
  const opts = { method, headers: { "Content-Type": "application/json", ...headers } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  let data;
  try { data = await res.json(); } catch { data = null; }
  return { status: res.status, data, headers: res.headers };
}

async function tests() {
  const userId = `int_${Date.now()}`;

  console.log(`\n=== Integration Tests (${BASE}) ===\n`);

  console.log("── Email integration ───────────────────");
  {
    const r = await req("POST", "/api/email/connect", {
      user_id: userId,
      provider: "smtp",
      action: "configure_smtp",
      account_email: "noreply@example.test",
      smtp_host: "smtp.example.test",
      smtp_port: 587,
      smtp_username: "user",
      smtp_password: "pass"
    });
    ok("POST /api/email/connect smtp configure → 200", r.status === 200);
    ok("smtp configure status", r.data?.status === "configured");
  }
  {
    const r = await req("POST", "/api/email/drafts", {
      user_id: userId,
      provider: "smtp",
      to: ["qa@example.test"],
      subject: "Draft test",
      body: "This is a saved draft from integrations test.",
      attachments: []
    });
    ok("POST /api/email/drafts → 200", r.status === 200);
    ok("draft_id returned", typeof r.data?.draft_id === "string");
  }
  {
    const r = await req("GET", `/api/email/drafts?user_id=${userId}`);
    ok("GET /api/email/drafts → 200", r.status === 200);
    ok("email drafts array", Array.isArray(r.data?.drafts));
  }
  {
    const r = await req("POST", "/api/email/send", {
      user_id: userId,
      provider: "smtp",
      to: ["qa@example.test"],
      subject: "Send-as-draft test",
      body: "Do not send externally.",
      save_as_draft: true,
      attachments: []
    });
    ok("POST /api/email/send save_as_draft → 200", r.status === 200);
  }
  {
    const r = await req("GET", `/api/email/inbox?user_id=${userId}&provider=smtp&limit=5`);
    ok("GET /api/email/inbox local → 200", r.status === 200);
    ok("inbox messages array", Array.isArray(r.data?.messages));
  }

  console.log("\n── Calendar integration ────────────────");
  {
    const start = new Date(Date.now() + 3600_000).toISOString();
    const end = new Date(Date.now() + 5400_000).toISOString();
    const r = await req("POST", "/api/calendar/events", {
      user_id: userId,
      provider: "local",
      title: "Integration Validation Event",
      description: "Local calendar flow test",
      start_time: start,
      end_time: end,
      timezone: "UTC",
      attendees: ["ops@example.test"],
      reminder_minutes: 10
    });
    ok("POST /api/calendar/events local → 200", r.status === 200);
    ok("calendar event id returned", typeof r.data?.event_id === "string");
  }
  {
    const r = await req("GET", `/api/calendar/events?user_id=${userId}&provider=local&limit=10`);
    ok("GET /api/calendar/events local → 200", r.status === 200);
    ok("calendar events array", Array.isArray(r.data?.events));
  }
  {
    const windowStart = new Date(Date.now() + 3000_000).toISOString();
    const windowEnd = new Date(Date.now() + 5 * 3600_000).toISOString();
    const r = await req("POST", "/api/calendar/schedule", {
      user_id: userId,
      title: "Scheduling assistant test",
      duration_minutes: 30,
      window_start: windowStart,
      window_end: windowEnd,
      provider: "local"
    });
    ok("POST /api/calendar/schedule → 200", r.status === 200);
    ok("schedule suggestions array", Array.isArray(r.data?.suggestions));
  }

  console.log("\n── Provider failover + diagnostics ─────");
  {
    const r = await req("GET", "/api/search?query=latest%20engineering%20news&news_mode=true");
    ok("GET /api/search news_mode=true → 200", r.status === 200);
    ok("search status field exists", typeof r.data?.status === "string");
    ok("search provider meta exists", typeof r.data?.meta?.provider === "string");
  }
  {
    const r = await req("GET", "/api/search/diagnostics");
    ok("GET /api/search/diagnostics → 200", r.status === 200);
    ok("diagnostics has fallback_events", typeof r.data?.diagnostics?.providers?.fallback_events === "number");
  }

  console.log(`\n${"─".repeat(46)}`);
  console.log(`Integration tests: ${pass} PASS  ${fail} FAIL`);
  if (errors.length) console.error("Failed:", errors.join(", "));
  process.exitCode = fail > 0 ? 1 : 0;
}

tests().catch(e => { console.error("Fatal:", e.message); process.exitCode = 1; });
