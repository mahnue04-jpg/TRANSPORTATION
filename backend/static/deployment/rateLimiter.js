"use strict";

/**
 * rateLimiter.js — Sliding window rate limiter with per-user quotas.
 */

const { uid, createRateLimitRecord } = require("./deploymentSchemas");

function createRateLimiter(options) {
  var config = Object.assign(
    {
      defaultMaxRequests: 100,
      defaultWindowMs:    60000,
      gcIntervalMs:       300000, // 5 minutes
    },
    options || {}
  );

  // key → [timestamp] (sliding window hit times)
  var windows = new Map();
  // userId → { quota config }
  var quotas = new Map();

  // Periodic GC of stale windows
  var gcTimer = setInterval(function () {
    var now = Date.now();
    windows.forEach(function (hits, key) {
      // Keep only keys with recent activity
      var recent = hits.filter(function (t) { return now - t < 3600000; }); // 1h
      if (recent.length === 0) windows.delete(key);
      else windows.set(key, recent);
    });
  }, config.gcIntervalMs);
  if (gcTimer.unref) gcTimer.unref();

  function getWindow(key) {
    if (!windows.has(key)) windows.set(key, []);
    return windows.get(key);
  }

  function pruneWindow(hits, windowMs) {
    var cutoff = Date.now() - windowMs;
    var i = 0;
    while (i < hits.length && hits[i] < cutoff) i++;
    if (i > 0) hits.splice(0, i);
  }

  /**
   * check(key, limitConfig) — returns { ok, remaining, resetAt, retryAfter }
   * Does NOT consume a token.
   */
  function check(key, limitConfig) {
    var lc = limitConfig || {};
    var maxRequests = lc.maxRequests || config.defaultMaxRequests;
    var windowMs    = lc.windowMs    || config.defaultWindowMs;

    var hits = getWindow(key);
    pruneWindow(hits, windowMs);

    var now = Date.now();
    var used = hits.length;
    var remaining = Math.max(0, maxRequests - used);
    var resetAt = hits.length > 0 ? hits[0] + windowMs : now + windowMs;

    return {
      ok:         remaining > 0,
      remaining,
      resetAt,
      retryAfter: remaining > 0 ? 0 : Math.max(0, resetAt - now),
      used,
      maxRequests,
    };
  }

  /**
   * consume(key, limitConfig) — check AND record a hit if allowed.
   */
  function consume(key, limitConfig) {
    var result = check(key, limitConfig);
    if (result.ok) {
      var hits = getWindow(key);
      hits.push(Date.now());
      // Return remaining after the consumed token
      result = Object.assign({}, result, {
        remaining: Math.max(0, result.remaining - 1),
        used:      result.used + 1,
      });
    }
    return result;
  }

  function reset(key) {
    windows.set(key, []);
    return { ok: true };
  }

  function getUsage(key) {
    var hits = getWindow(key);
    pruneWindow(hits, config.defaultWindowMs);
    return { key, used: hits.length, windowMs: config.defaultWindowMs };
  }

  /**
   * setQuota(userId, quotaConfig) — set per-user quota rules.
   * quotaConfig: { daily: N, hourly: N, perTool: { toolName: N } }
   */
  function setQuota(userId, quotaConfig) {
    quotas.set(userId, Object.assign({}, quotaConfig || {}));
    return { ok: true };
  }

  /**
   * checkQuota(userId, type) — check quota for a specific type.
   * type: "daily" | "hourly" | "perTool:toolName" | "concurrent"
   */
  function checkQuota(userId, type) {
    var quota = quotas.get(userId);
    if (!quota) return { ok: true, message: "No quota configured" };

    if (type === "daily") {
      var dayMs = 24 * 60 * 60 * 1000;
      return consume(userId + ":daily", { maxRequests: quota.daily || 10000, windowMs: dayMs });
    }
    if (type === "hourly") {
      var hourMs = 60 * 60 * 1000;
      return consume(userId + ":hourly", { maxRequests: quota.hourly || 1000, windowMs: hourMs });
    }
    if (type && type.startsWith("perTool:")) {
      var toolName = type.slice("perTool:".length);
      var perTool = (quota.perTool && quota.perTool[toolName]) || 60;
      return consume(userId + ":tool:" + toolName, { maxRequests: perTool, windowMs: 60000 });
    }
    return { ok: true, message: "Unknown quota type: " + type };
  }

  function destroy() {
    clearInterval(gcTimer);
    windows.clear();
    quotas.clear();
  }

  return {
    check,
    consume,
    reset,
    getUsage,
    setQuota,
    checkQuota,
    destroy,
  };
}

module.exports = { createRateLimiter };
