#!/usr/bin/env node
// runRuntimeBenchmarks.js — npm run benchmark:runtime
// Latency benchmarks: chat, upload, auth, streaming, admin endpoints.

const BASE     = process.env.API_URL     || "http://127.0.0.1:8000";
const REPS     = parseInt(process.env.BENCH_REPS || "10", 10);
const TIMEOUT  = parseInt(process.env.BENCH_TIMEOUT || "15000", 10);

async function req(method, path, body, headers = {}) {
  const ctrl = new AbortController();
  const tid   = setTimeout(() => ctrl.abort(), TIMEOUT);
  const opts  = {
    method,
    headers: { "Content-Type": "application/json", ...headers },
    signal: ctrl.signal,
  };
  if (body) opts.body = JSON.stringify(body);
  try {
    const t0  = performance.now();
    const res = await fetch(`${BASE}${path}`, opts);
    const ms  = performance.now() - t0;
    clearTimeout(tid);
    return { ok: res.ok, status: res.status, ms };
  } catch (e) {
    clearTimeout(tid);
    return { ok: false, status: 0, ms: TIMEOUT, error: e.message };
  }
}

async function bench(label, fn, reps = REPS) {
  const samples = [];
  let   errors  = 0;
  process.stdout.write(`  ${label.padEnd(35)} `);
  for (let i = 0; i < reps; i++) {
    const r = await fn();
    if (r.ok) samples.push(r.ms);
    else       errors++;
  }
  samples.sort((a, b) => a - b);
  const n   = samples.length;
  const avg = n ? (samples.reduce((s, x) => s + x, 0) / n).toFixed(0) : "—";
  const p50 = n ? samples[Math.floor(n * 0.5)].toFixed(0) : "—";
  const p95 = n ? samples[Math.floor(n * 0.95)].toFixed(0) : "—";
  const min = n ? samples[0].toFixed(0) : "—";
  const max = n ? samples[n - 1].toFixed(0) : "—";
  console.log(`avg=${String(avg).padStart(5)}ms  p50=${String(p50).padStart(5)}ms  p95=${String(p95).padStart(5)}ms  min=${String(min).padStart(5)}ms  max=${String(max).padStart(5)}ms  err=${errors}/${reps}`);
  return { label, avg: +avg, p50: +p50, p95: +p95, min: +min, max: +max, errors, n };
}

async function main() {
  console.log(`\n=== Runtime Benchmarks  (${BASE})  reps=${REPS} ===\n`);

  const results = [];

  // ── Health / baseline ─────────────────────────────────────────────────────
  results.push(await bench("GET /api/health",
    () => req("GET", "/api/health")));

  results.push(await bench("GET /api/admin/metrics",
    () => req("GET", "/api/admin/metrics")));

  results.push(await bench("GET /api/admin/dashboard",
    () => req("GET", "/api/admin/dashboard")));

  // ── Auth ──────────────────────────────────────────────────────────────────
  // Pre-register a user so login is a real auth hit
  const email    = `bench_${Date.now()}@bench.test`;
  const password = `Bench!${Date.now()}`;
  await req("POST", "/api/auth/register", { email, password });

  results.push(await bench("POST /api/auth/login",
    () => req("POST", "/api/auth/login", { email, password })));

  results.push(await bench("POST /api/auth/login (wrong creds)",
    () => req("POST", "/api/auth/login", { email, password: "wrong" })));

  // ── Chat ──────────────────────────────────────────────────────────────────
  const uid = `bench_${Date.now()}`;
  results.push(await bench("POST /api/chat (short message)",
    () => req("POST", "/api/chat", { message: "hi", user_id: uid })));

  results.push(await bench("POST /api/chat (longer message)",
    () => req("POST", "/api/chat", {
      message: "What is the capital of France? Answer in one word.",
      user_id: uid,
    })));

  // ── Upload ────────────────────────────────────────────────────────────────
  results.push(await bench("POST /api/upload (1 KB text)",
    async () => {
      const form = new FormData();
      form.append("file", new Blob(["a".repeat(1024)], { type: "text/plain" }), "bench.txt");
      const t0  = performance.now();
      const res = await fetch(`${BASE}/api/upload`, { method: "POST", body: form });
      return { ok: res.ok, status: res.status, ms: performance.now() - t0 };
    }));

  // ── Provider diagnostics ──────────────────────────────────────────────────
  results.push(await bench("GET /api/diagnostics/providers",
    () => req("GET", "/api/diagnostics/providers")));

  // ── Summary table ─────────────────────────────────────────────────────────
  console.log(`\n${"─".repeat(80)}`);
  console.log("SUMMARY");
  console.log(`${"─".repeat(80)}`);
  const cols = ["label", "avg", "p50", "p95", "max", "errors"];
  console.log(
    "Endpoint".padEnd(36) +
    "Avg(ms)".padStart(10) +
    "P50(ms)".padStart(10) +
    "P95(ms)".padStart(10) +
    "Max(ms)".padStart(10) +
    "Errors".padStart(10)
  );
  console.log("─".repeat(80));
  for (const r of results) {
    console.log(
      r.label.padEnd(36) +
      String(r.avg).padStart(10) +
      String(r.p50).padStart(10) +
      String(r.p95).padStart(10) +
      String(r.max).padStart(10) +
      `${r.errors}/${REPS}`.padStart(10)
    );
  }
  console.log(`${"─".repeat(80)}\n`);

  // ── Circuit breaker snapshot ──────────────────────────────────────────────
  try {
    const r = await req("GET", "/api/diagnostics/providers");
    if (r.ok) {
      const data = await (await fetch(`${BASE}/api/diagnostics/providers`)).json();
      console.log("Circuit Breaker Snapshot:");
      for (const [name, p] of Object.entries(data.providers ?? {})) {
        const health = typeof p.health_score === "number"
          ? `health=${(p.health_score * 100).toFixed(0)}%`
          : "";
        console.log(`  ${name.padEnd(20)}  state=${p.state}  ${health}`);
      }
      console.log();
    }
  } catch {}

  process.exitCode = 0;
}

main().catch(e => { console.error("Fatal:", e.message); process.exitCode = 1; });
