/**
 * Provider Benchmarks — response times, fallback frequency, health scoring
 * Run: npm run benchmark:providers
 * Requires backend running on http://127.0.0.1:8000
 */

"use strict";

const http = require("http");

const BASE_URL = "http://127.0.0.1:8000";

function httpPost(path, body) {
  return new Promise((resolve, reject) => {
    const raw = JSON.stringify(body);
    const opts = {
      hostname: "127.0.0.1", port: 8000, path, method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(raw) },
    };
    const t0 = Date.now();
    const req = http.request(opts, res => {
      let data = "";
      res.on("data", c => { data += c; });
      res.on("end", () => {
        const durationMs = Date.now() - t0;
        try { resolve({ status: res.statusCode, body: JSON.parse(data), durationMs }); }
        catch { resolve({ status: res.statusCode, body: data, durationMs }); }
      });
    });
    req.on("error", reject);
    req.write(raw);
    req.end();
  });
}

function httpGet(path) {
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    http.get(`http://127.0.0.1:8000${path}`, res => {
      let data = "";
      res.on("data", c => { data += c; });
      res.on("end", () => {
        const durationMs = Date.now() - t0;
        try { resolve({ status: res.statusCode, body: JSON.parse(data), durationMs }); }
        catch { resolve({ status: res.statusCode, body: data, durationMs }); }
      });
    }).on("error", reject);
  });
}

function pad(s, n) { return String(s).padEnd(n); }
function padL(s, n) { return String(s).padStart(n); }

async function benchmarkRoute(label, message, runs = 3) {
  const times = [];
  let errors = 0;
  let provider = "?";
  let status   = "?";

  for (let i = 0; i < runs; i++) {
    try {
      const res = await httpPost("/api/chat", { user_id: "bench_user", message });
      times.push(res.durationMs);
      if (res.body && res.body.meta && res.body.meta.provider) provider = res.body.meta.provider;
      if (res.body && res.body.status) status = res.body.status;
      if (res.status !== 200) errors++;
    } catch (err) {
      errors++;
      times.push(9999);
    }
  }

  const avg  = Math.round(times.reduce((a, b) => a + b, 0) / times.length);
  const min  = Math.min(...times);
  const max  = Math.max(...times);
  return { label, avg, min, max, errors, runs, provider, status };
}

async function run() {
  console.log("═══════════════════════════════════════════════════════════");
  console.log("  Amicore Provider Benchmarks");
  console.log("═══════════════════════════════════════════════════════════");
  console.log("");

  const RUNS = 2; // keep light — these hit real external APIs
  const benchmarks = [
    { label: "Weather (London)",     message: "What is the weather in London?" },
    { label: "Weather (New York)",   message: "What is the weather in New York?" },
    { label: "Search (AI trends)",   message: "Search: latest AI trends 2025" },
    { label: "News (technology)",    message: "Show me technology news" },
    { label: "Time (Tokyo)",         message: "What time is it in Tokyo?" },
    { label: "Chat (simple)",        message: "Say hello in one word." },
  ];

  const results = [];
  for (const bm of benchmarks) {
    process.stdout.write(`  Benchmarking: ${bm.label}…`);
    try {
      const r = await benchmarkRoute(bm.label, bm.message, RUNS);
      results.push(r);
      console.log(` avg=${r.avg}ms`);
    } catch (err) {
      console.log(` ERROR: ${err.message}`);
      results.push({ label: bm.label, avg: "ERR", min: "ERR", max: "ERR", errors: RUNS, runs: RUNS, provider: "?", status: "error" });
    }
  }

  // Provider health snapshot
  let healthSnapshot = null;
  try {
    const hr = await httpGet("/api/diagnostics/providers");
    if (hr.body && hr.body.providers) healthSnapshot = hr.body.providers;
  } catch {}

  console.log("");
  console.log("───────────────────────────────────────────────────────────");
  console.log(`  ${pad("Capability", 22)} ${padL("Avg", 7)} ${padL("Min", 7)} ${padL("Max", 7)} ${pad("Provider", 12)} ${pad("Status", 10)}`);
  console.log("───────────────────────────────────────────────────────────");
  for (const r of results) {
    const avgStr = r.avg === "ERR" ? "  ERR" : `${r.avg}ms`;
    const minStr = r.min === "ERR" ? "  ERR" : `${r.min}ms`;
    const maxStr = r.max === "ERR" ? "  ERR" : `${r.max}ms`;
    const errMark = r.errors > 0 ? ` (!${r.errors}err)` : "";
    console.log(
      `  ${pad(r.label, 22)} ${padL(avgStr, 7)} ${padL(minStr, 7)} ${padL(maxStr, 7)} ${pad(r.provider, 12)} ${r.status}${errMark}`
    );
  }

  if (healthSnapshot) {
    console.log("");
    console.log("  Provider Circuit Breaker States:");
    console.log("  ─────────────────────────────────────────");
    for (const [name, info] of Object.entries(healthSnapshot)) {
      const health = typeof info.health_score === "number" ? `${(info.health_score * 100).toFixed(0)}%` : "?";
      console.log(`    ${pad(name, 18)} state=${pad(info.state, 10)} health=${health} calls=${info.total_calls}`);
    }
  }

  console.log("───────────────────────────────────────────────────────────");
  const totalErrors = results.reduce((acc, r) => acc + (r.errors || 0), 0);
  if (totalErrors > 0) {
    console.log(`  ⚠  ${totalErrors} errors across all benchmarks`);
  } else {
    console.log("  All benchmarks completed successfully.");
  }
}

run().catch(err => { console.error("Benchmark failed:", err); process.exit(1); });
