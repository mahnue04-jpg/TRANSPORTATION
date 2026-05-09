"use strict";

/**
 * healthMonitor.js — Pluggable health check runner for all subsystems.
 */

const { HEALTH_STATUSES, uid, createHealthReport } = require("./deploymentSchemas");

function createHealthMonitor(options) {
  var config = Object.assign(
    {
      version: "1.0.0",
      timeoutMs: 5000,
    },
    options || {}
  );

  // name → async fn() → { healthy: bool, message: string, details: {} }
  var checks = new Map();
  var lastReport = null;

  function registerCheck(name, fn) {
    if (typeof fn !== "function") throw new Error("Health check must be a function: " + name);
    checks.set(name, fn);
  }

  function unregisterCheck(name) { checks.delete(name); }

  async function runCheck(name) {
    var fn = checks.get(name);
    if (!fn) return { name, healthy: false, message: "Check not found: " + name, durationMs: 0 };

    var start = Date.now();
    var timedOut = false;

    try {
      var result = await Promise.race([
        fn(),
        new Promise(function (_, reject) {
          setTimeout(function () {
            timedOut = true;
            reject(new Error("Health check timed out: " + name));
          }, config.timeoutMs);
        }),
      ]);

      var elapsed = Date.now() - start;
      var healthy = !result || result.healthy !== false;

      return {
        name,
        healthy,
        message: (result && result.message) || (healthy ? "ok" : "failed"),
        details: (result && result.details) || {},
        durationMs: elapsed,
      };
    } catch (err) {
      return {
        name,
        healthy: false,
        message: timedOut ? "Timed out" : ((err && err.message) || "Check threw error"),
        details: {},
        durationMs: Date.now() - start,
      };
    }
  }

  async function runAll() {
    if (checks.size === 0) {
      lastReport = createHealthReport({ status: HEALTH_STATUSES.healthy, checks: {}, version: config.version });
      return lastReport;
    }

    var names = Array.from(checks.keys());
    var results = await Promise.all(names.map(runCheck));

    var checksMap = {};
    var passCount = 0;
    var failCount = 0;

    results.forEach(function (r) {
      checksMap[r.name] = { healthy: r.healthy, message: r.message, details: r.details, durationMs: r.durationMs };
      if (r.healthy) passCount++; else failCount++;
    });

    var status;
    if (failCount === 0) status = HEALTH_STATUSES.healthy;
    else if (passCount === 0) status = HEALTH_STATUSES.unhealthy;
    else status = HEALTH_STATUSES.degraded;

    lastReport = createHealthReport({ status, checks: checksMap, version: config.version });
    return lastReport;
  }

  function getReport() { return lastReport; }
  function getStatus() { return lastReport ? lastReport.status : null; }
  function checkCount() { return checks.size; }

  return {
    registerCheck,
    unregisterCheck,
    runCheck,
    runAll,
    getReport,
    getStatus,
    checkCount,
    HEALTH_STATUSES,
  };
}

module.exports = { createHealthMonitor };
