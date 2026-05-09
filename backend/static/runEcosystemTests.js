#!/usr/bin/env node
// runEcosystemTests.js — npm run test:ecosystem

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
  const userId = `eco_${Date.now()}`;

  console.log(`\n=== Ecosystem Tests (${BASE}) ===\n`);

  console.log("── Search layer ─────────────────────────");
  {
    const r = await req("GET", "/api/search?query=latest%20ai%20infrastructure");
    ok("GET /api/search → 200", r.status === 200);
    ok("search has status", typeof r.data?.status === "string");
    ok("search has sources array", Array.isArray(r.data?.sources));
  }
  {
    const r = await req("GET", "/api/search/diagnostics");
    ok("GET /api/search/diagnostics → 200", r.status === 200);
    ok("diagnostics.cache exists", r.data?.diagnostics?.cache != null);
    ok("diagnostics.providers exists", r.data?.diagnostics?.providers != null);
  }

  console.log("\n── Memory evolution ─────────────────────");
  {
    const r = await req("POST", "/api/memory/index", {
      user_id: userId,
      source: "conversation",
      text: "Amicor should remember integration context, user preferences, and deployment details for follow-up execution.",
      priority: 0.9,
    });
    ok("POST /api/memory/index → 200", r.status === 200);
    ok("memory index returns chunks", (r.data?.chunks ?? 0) >= 1);
  }
  {
    const r = await req("GET", `/api/memory/retrieve?user_id=${userId}&query=deployment%20details&top_k=3`);
    ok("GET /api/memory/retrieve → 200", r.status === 200);
    ok("memory retrieve returns results", Array.isArray(r.data?.results));
  }
  {
    // Build history first
    await req("POST", "/api/chat", { user_id: userId, message: "Please summarize my ecosystem integration plans" });
    const r = await req("POST", "/api/memory/compress", { user_id: userId });
    ok("POST /api/memory/compress → 200", r.status === 200);
    ok("memory summary string", typeof r.data?.summary === "string" || r.data?.summary === null);
  }

  console.log("\n── Workflow system ──────────────────────");
  let workflowId = null;
  {
    const r = await req("POST", "/api/workflows", {
      user_id: userId,
      name: "Daily Ops",
      description: "Search + chat chain",
      reusable_prompt: "Summarize findings",
      action_chain: [
        { type: "search", prompt: "latest cloud runtime reliability updates" },
        { type: "chat", prompt: "Create action list from {{input}}" }
      ]
    });
    ok("POST /api/workflows → 200", r.status === 200);
    workflowId = r.data?.workflow_id;
    ok("workflow_id returned", typeof workflowId === "string");
  }
  {
    const r = await req("GET", `/api/workflows?user_id=${userId}`);
    ok("GET /api/workflows → 200", r.status === 200);
    ok("workflows array", Array.isArray(r.data?.workflows));
  }
  {
    const r = await req("POST", `/api/workflows/${workflowId}/execute`, {
      user_id: userId,
      input_text: "integration telemetry and deployment checklist"
    });
    ok("POST /api/workflows/{id}/execute → 200", r.status === 200);
    ok("workflow run has steps", Array.isArray(r.data?.step_results));
  }
  {
    const r = await req("GET", `/api/workflows/${workflowId}/history?user_id=${userId}&limit=5`);
    ok("GET /api/workflows/{id}/history → 200", r.status === 200);
    ok("workflow history array", Array.isArray(r.data?.runs));
  }

  console.log("\n── File intelligence ────────────────────");
  {
    const form = new FormData();
    form.append("file", new Blob(["name,role\nAmicor,assistant\n"], { type: "text/csv" }), "sample.csv");
    const res = await fetch(`${BASE}/api/upload`, { method: "POST", body: form });
    const data = await res.json();
    ok("POST /api/upload CSV → 200", res.status === 200);
    ok("upload_category present", typeof data?.upload_category === "string");
    ok("document_summary present", data?.document_summary == null || typeof data?.document_summary === "string");
  }

  console.log("\n── PWA baseline ─────────────────────────");
  {
    const res = await fetch(`${BASE}/static/manifest.webmanifest`);
    ok("GET /static/manifest.webmanifest → 200", res.status === 200);
  }

  console.log(`\n${"─".repeat(46)}`);
  console.log(`Ecosystem tests: ${pass} PASS  ${fail} FAIL`);
  if (errors.length) console.error("Failed:", errors.join(", "));
  process.exitCode = fail > 0 ? 1 : 0;
}

tests().catch(e => { console.error("Fatal:", e.message); process.exitCode = 1; });
