"use strict";

/**
 * telemetry.js — Distributed tracing and metrics collection.
 * Ring buffers for spans and metrics; pluggable flush transport.
 */

const { uid, createSpan, createMetricSample, SPAN_STATUS, METRIC_TYPES } = require("./deploymentSchemas");

const SPAN_RING_SIZE   = 500;
const METRIC_RING_SIZE = 1000;

function createTelemetry(options) {
  var config = Object.assign({ serviceName: "amicore", version: "1.0.0" }, options || {});

  var spans       = [];
  var metrics     = [];
  var activeSpans = new Map();  // spanId → span

  function startSpan(name, context) {
    var ctx = context || {};
    var span = createSpan({
      name,
      parentId: ctx.parentId || null,
      traceId:  ctx.traceId  || uid("trace"),
      tags:     ctx.tags     || {},
      data:     ctx.data     || {},
    });
    activeSpans.set(span.id, span);
    return span.id;
  }

  function endSpan(spanId, result) {
    var span = activeSpans.get(spanId);
    if (!span) return null;
    activeSpans.delete(spanId);

    span.endTime   = Date.now();
    span.durationMs = span.endTime - span.startTime;

    var res = result || {};
    if (res.error) {
      span.status = SPAN_STATUS.error;
      span.error  = { message: res.error.message || String(res.error), code: res.error.code };
    } else {
      span.status = SPAN_STATUS.ok;
    }

    if (res.data) Object.assign(span.data, res.data);
    if (res.tags) Object.assign(span.tags, res.tags);

    spans.push(span);
    if (spans.length > SPAN_RING_SIZE) spans.shift();

    return span;
  }

  function recordMetric(name, value, tags) {
    var sample = createMetricSample({ name, value, tags: tags || {}, type: METRIC_TYPES.gauge });
    metrics.push(sample);
    if (metrics.length > METRIC_RING_SIZE) metrics.shift();
    return sample;
  }

  function increment(name, tags) {
    var sample = createMetricSample({ name, value: 1, tags: tags || {}, type: METRIC_TYPES.counter });
    metrics.push(sample);
    if (metrics.length > METRIC_RING_SIZE) metrics.shift();
    return sample;
  }

  function recordWorkflowEvent(workflowId, event, data) {
    return recordMetric("workflow.event", 1, { workflowId, event: event || "unknown" });
  }

  function getSpans(filter) {
    var result = spans.slice();
    if (!filter) return result;
    if (filter.name)    result = result.filter(function (s) { return s.name === filter.name; });
    if (filter.traceId) result = result.filter(function (s) { return s.traceId === filter.traceId; });
    if (filter.status)  result = result.filter(function (s) { return s.status === filter.status; });
    if (filter.since)   result = result.filter(function (s) { return s.startTime >= filter.since; });
    return result;
  }

  function getMetrics(filter) {
    var result = metrics.slice();
    if (!filter) return result;
    if (filter.name)  result = result.filter(function (m) { return m.name === filter.name; });
    if (filter.since) result = result.filter(function (m) { return m.timestamp >= filter.since; });
    if (filter.tags) {
      var fTags = filter.tags;
      result = result.filter(function (m) {
        return Object.keys(fTags).every(function (k) { return m.tags[k] === fTags[k]; });
      });
    }
    return result;
  }

  function flush(transport) {
    if (typeof transport !== "function") return;
    transport({ spans: spans.slice(), metrics: metrics.slice(), timestamp: Date.now() });
  }

  function activeSpanCount() { return activeSpans.size; }

  function clearAll() { spans = []; metrics = []; activeSpans.clear(); }

  return {
    startSpan,
    endSpan,
    recordMetric,
    increment,
    recordWorkflowEvent,
    getSpans,
    getMetrics,
    flush,
    activeSpanCount,
    clearAll,
    SPAN_STATUS,
    METRIC_TYPES,
  };
}

module.exports = { createTelemetry };
