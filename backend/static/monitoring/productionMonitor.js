"use strict";
/**
 * productionMonitor.js — Client-side production monitoring hooks for Amicor.
 *
 * Exposes: window.AmiCorMonitor
 *
 * Collects:
 *   - Response time per API call (p50 / p95 / p99 computed on demand)
 *   - Error rate (errors / total requests in rolling 5-min window)
 *   - Session duration
 *   - Active user indicator (last interaction timestamp)
 *
 * Heartbeat:
 *   - Periodic GET to /api/health (default every 60 s)
 *   - If health check fails, dispatches a custom DOM event "amicor:health-fail"
 *     and notifies AmiCorErrorRecovery if present.
 *
 * Dashboard hooks:
 *   - AmiCorMonitor.getReport() returns a snapshot object.
 *   - AmiCorMonitor.subscribe(fn) calls fn(report) on every metric update.
 *   - A hidden <div id="amicor-monitor-data"> always holds the latest JSON
 *     for external scraping (browser extensions, Playwright tests, etc.).
 */

;(function (global) {

  const RING_SIZE        = 200;      // max response-time samples kept
  const HEARTBEAT_MS     = 60_000;   // health-check interval
  const WINDOW_MS        = 5 * 60_000; // 5-min rolling error-rate window
  const DATA_EL_ID       = "amicor-monitor-data";

  // ── Ring buffer ─────────────────────────────────────────────────────────────
  function createRing(size) {
    const buf = [];
    return {
      push(v)  { buf.push(v); if (buf.length > size) buf.shift(); },
      values() { return [...buf]; },
      size()   { return buf.length; },
    };
  }

  // ── Percentile ───────────────────────────────────────────────────────────────
  function percentile(sorted, p) {
    if (!sorted.length) return 0;
    const i = Math.ceil(sorted.length * p / 100) - 1;
    return sorted[Math.max(0, Math.min(i, sorted.length - 1))];
  }

  // ── State ────────────────────────────────────────────────────────────────────
  const responseTimes = createRing(RING_SIZE);
  const events        = [];        // { type:'req'|'error', ts:ms }
  let   sessionStart  = Date.now();
  let   lastActivity  = Date.now();
  let   heartbeatTimer = null;
  let   heartbeatOk    = true;
  const subscribers    = [];

  // ── Persistence: mirror report into DOM data attribute ───────────────────────
  function getOrCreateDataEl() {
    if (typeof document === "undefined") return null;
    let el = document.getElementById(DATA_EL_ID);
    if (!el) {
      el = document.createElement("div");
      el.id    = DATA_EL_ID;
      el.style.display = "none";
      el.setAttribute("aria-hidden", "true");
      document.body && document.body.appendChild(el);
    }
    return el;
  }

  function persistReport(report) {
    try {
      const el = getOrCreateDataEl();
      if (el) el.setAttribute("data-report", JSON.stringify(report));
    } catch (_) {}
    subscribers.forEach(fn => { try { fn(report); } catch (_) {} });
  }

  // ── Report builder ───────────────────────────────────────────────────────────
  function buildReport() {
    const now   = Date.now();
    const times = responseTimes.values().sort((a, b) => a - b);

    // Rolling 5-min window
    const cutoff      = now - WINDOW_MS;
    const windowEvents = events.filter(e => e.ts >= cutoff);
    const totalReqs    = windowEvents.filter(e => e.type === "req").length;
    const errorReqs    = windowEvents.filter(e => e.type === "error").length;
    const errorRate    = totalReqs > 0 ? (errorReqs / totalReqs) : 0;

    return {
      timestamp:       now,
      sessionDurationMs: now - sessionStart,
      idleMs:          now - lastActivity,
      heartbeatOk,
      responseTimes: {
        samples: times.length,
        p50:     Math.round(percentile(times, 50)),
        p95:     Math.round(percentile(times, 95)),
        p99:     Math.round(percentile(times, 99)),
        avg:     times.length
          ? Math.round(times.reduce((a, b) => a + b, 0) / times.length)
          : 0,
      },
      errorRate:    parseFloat(errorRate.toFixed(4)),
      totalRequests: totalReqs,
      errorCount:    errorReqs,
    };
  }

  // ── Recording helpers ────────────────────────────────────────────────────────
  function recordRequest(durationMs, isError) {
    lastActivity = Date.now();
    responseTimes.push(durationMs);
    events.push({ type: "req",   ts: Date.now() });
    if (isError) events.push({ type: "error", ts: Date.now() });

    // Prune old events (older than WINDOW_MS * 2 to avoid unbounded growth)
    const cutoff = Date.now() - WINDOW_MS * 2;
    while (events.length && events[0].ts < cutoff) events.shift();

    const report = buildReport();
    persistReport(report);
    return report;
  }

  // ── Heartbeat ────────────────────────────────────────────────────────────────
  async function doHeartbeat() {
    try {
      const start = Date.now();
      const res   = await fetch("/api/health", { method: "GET", cache: "no-store" });
      const ms    = Date.now() - start;
      heartbeatOk = res.ok;
      recordRequest(ms, !res.ok);

      if (!res.ok) {
        dispatchHealthFail(`/api/health returned HTTP ${res.status}`);
      }
    } catch (err) {
      heartbeatOk = false;
      recordRequest(0, true);
      dispatchHealthFail(err.message || "network error");
    }
  }

  function dispatchHealthFail(reason) {
    if (typeof document !== "undefined") {
      document.dispatchEvent(new CustomEvent("amicor:health-fail", { detail: { reason } }));
    }
    if (global.AmiCorErrorRecovery) {
      global.AmiCorErrorRecovery.notify("⚠️ Health check failed — server may be unavailable", "warn");
    }
  }

  // ── Public API ───────────────────────────────────────────────────────────────
  const AmiCorMonitor = {
    /**
     * start({ heartbeatMs })
     *   Begins periodic heartbeat checks.
     *   Call once after the app is loaded.
     */
    start({ heartbeatMs = HEARTBEAT_MS } = {}) {
      sessionStart = Date.now();
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      // Run first heartbeat after a short delay so the page can finish loading
      setTimeout(doHeartbeat, 3000);
      heartbeatTimer = setInterval(doHeartbeat, heartbeatMs);
      if (typeof heartbeatTimer === "object" && heartbeatTimer.unref) {
        heartbeatTimer.unref(); // Node.js: don't block process exit
      }
      return this;
    },

    stop() {
      if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
    },

    /**
     * record(durationMs, isError)
     *   Call this after every /api/chat or /api/upload request.
     */
    record(durationMs, isError = false) {
      return recordRequest(durationMs, isError);
    },

    /**
     * trackActivity()
     *   Call on any user interaction to update the idle timer.
     */
    trackActivity() {
      lastActivity = Date.now();
    },

    /** Return a current performance report snapshot. */
    getReport() { return buildReport(); },

    /**
     * subscribe(fn)
     *   fn(report) called on every metric update.
     *   Returns unsubscribe function.
     */
    subscribe(fn) {
      subscribers.push(fn);
      return () => {
        const i = subscribers.indexOf(fn);
        if (i !== -1) subscribers.splice(i, 1);
      };
    },
  };

  global.AmiCorMonitor = AmiCorMonitor;
  if (typeof module !== "undefined") module.exports = AmiCorMonitor;

}(typeof window !== "undefined" ? window : global));
