"use strict";

/**
 * errorMonitor.js — Error capture, deduplication, hooks, and rate tracking.
 */

const crypto = require("crypto");
const { uid, createErrorRecord } = require("./deploymentSchemas");

const RING_SIZE = 500;

function fingerprint(err) {
  var msg = (err && err.message) ? err.message : String(err);
  var frame = "";
  if (err && err.stack) {
    var lines = err.stack.split("\n");
    // Find first non-error frame
    for (var i = 0; i < lines.length; i++) {
      if (lines[i].trim().startsWith("at ")) { frame = lines[i].trim(); break; }
    }
  }
  return crypto.createHash("md5").update(msg + "|" + frame).digest("hex").slice(0, 16);
}

function createErrorMonitor(options) {
  var config = Object.assign(
    {
      captureUnhandled: false,
      maxErrors:        RING_SIZE,
    },
    options || {}
  );

  var errorLog = [];
  // fingerprint → errorRecord (for deduplication)
  var dedupMap = new Map();
  var hooks = [];

  function capture(error, context) {
    var err = error instanceof Error ? error : (typeof error === "object" ? error : new Error(String(error)));
    var fp = fingerprint(err);
    var existing = dedupMap.get(fp);

    if (existing) {
      existing.count += 1;
      existing.lastSeenAt = Date.now();
      for (var i = 0; i < hooks.length; i++) { try { hooks[i](existing); } catch (_) {} }
      return existing;
    }

    var record = createErrorRecord({ error: err, context: context || {}, severity: (context && context.severity) || "error" });
    record.fingerprint = fp;
    record.lastSeenAt = Date.now();

    errorLog.push(record);
    if (errorLog.length > config.maxErrors) {
      var removed = errorLog.shift();
      dedupMap.delete(removed.fingerprint);
    }

    dedupMap.set(fp, record);

    for (var j = 0; j < hooks.length; j++) { try { hooks[j](record); } catch (_) {} }

    return record;
  }

  function addHook(fn) {
    if (typeof fn === "function") hooks.push(fn);
  }

  function getErrors(filter) {
    var result = errorLog.slice();
    if (!filter) return result;
    if (filter.severity) result = result.filter(function (e) { return e.severity === filter.severity; });
    if (filter.since)    result = result.filter(function (e) { return e.timestamp >= filter.since; });
    if (filter.code)     result = result.filter(function (e) { return e.code === filter.code; });
    return result;
  }

  function clearErrors() {
    errorLog = [];
    dedupMap.clear();
  }

  function errorCount() { return errorLog.length; }

  /**
   * getErrorRate(windowMs) — errors per second in the given window.
   */
  function getErrorRate(windowMs) {
    var window = windowMs || 60000;
    var cutoff = Date.now() - window;
    var recent = errorLog.filter(function (e) { return e.timestamp >= cutoff; });
    return { count: recent.length, ratePerSecond: recent.length / (window / 1000), windowMs: window };
  }

  return {
    capture,
    addHook,
    getErrors,
    clearErrors,
    errorCount,
    getErrorRate,
  };
}

module.exports = { createErrorMonitor };
