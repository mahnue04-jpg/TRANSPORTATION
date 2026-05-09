"use strict";

/**
 * deploymentSchemas.js — Shared enums and factories for deployment modules.
 */

const crypto = require("crypto");

const ENVIRONMENTS = { dev: "dev", staging: "staging", production: "production" };

const LOG_LEVELS = { debug: "debug", info: "info", warn: "warn", error: "error", fatal: "fatal" };

const LOG_LEVEL_RANK = { debug: 0, info: 1, warn: 2, error: 3, fatal: 4 };

const HEALTH_STATUSES = { healthy: "healthy", degraded: "degraded", unhealthy: "unhealthy" };

const METRIC_TYPES = { counter: "counter", gauge: "gauge", histogram: "histogram", timer: "timer" };

const SPAN_STATUS = { started: "started", ok: "ok", error: "error" };

function uid(prefix) {
  return (prefix || "id") + "_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
}

function createLogEntry(options) {
  var opts = options || {};
  return {
    id:        uid("log"),
    timestamp: Date.now(),
    level:     opts.level || LOG_LEVELS.info,
    message:   opts.message || "",
    context:   Object.assign({}, opts.context || {}),
    requestId: opts.requestId || null,
    traceId:   opts.traceId || null,
    spanId:    opts.spanId || null,
    error:     opts.error || null,
  };
}

function createHealthReport(options) {
  var opts = options || {};
  return {
    status:    opts.status || HEALTH_STATUSES.healthy,
    checks:    opts.checks || {},
    timestamp: Date.now(),
    version:   opts.version || "1.0.0",
  };
}

function createMetricSample(options) {
  var opts = options || {};
  return {
    id:        uid("metric"),
    name:      opts.name || "unknown",
    type:      opts.type || METRIC_TYPES.gauge,
    value:     opts.value !== undefined ? opts.value : 0,
    tags:      Object.assign({}, opts.tags || {}),
    timestamp: Date.now(),
  };
}

function createRateLimitRecord(options) {
  var opts = options || {};
  return {
    key:        opts.key || "default",
    count:      opts.count || 0,
    windowStart: opts.windowStart || Date.now(),
    windowMs:   opts.windowMs || 60000,
    maxRequests: opts.maxRequests || 100,
    resetAt:    (opts.windowStart || Date.now()) + (opts.windowMs || 60000),
  };
}

function createSpan(options) {
  var opts = options || {};
  return {
    id:         uid("span"),
    name:       opts.name || "unknown",
    parentId:   opts.parentId || null,
    traceId:    opts.traceId || uid("trace"),
    startTime:  Date.now(),
    endTime:    null,
    durationMs: null,
    status:     SPAN_STATUS.started,
    tags:       Object.assign({}, opts.tags || {}),
    data:       Object.assign({}, opts.data || {}),
    error:      null,
  };
}

function createErrorRecord(options) {
  var opts = options || {};
  var err = opts.error || {};
  return {
    id:          uid("err"),
    message:     (err.message) || String(err) || "Unknown error",
    stack:       err.stack || null,
    code:        err.code || opts.code || null,
    context:     Object.assign({}, opts.context || {}),
    severity:    opts.severity || "error",
    timestamp:   Date.now(),
    fingerprint: null,  // set by errorMonitor
    count:       1,
  };
}

module.exports = {
  ENVIRONMENTS,
  LOG_LEVELS,
  LOG_LEVEL_RANK,
  HEALTH_STATUSES,
  METRIC_TYPES,
  SPAN_STATUS,
  uid,
  createLogEntry,
  createHealthReport,
  createMetricSample,
  createRateLimitRecord,
  createSpan,
  createErrorRecord,
};
