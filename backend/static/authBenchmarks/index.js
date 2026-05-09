"use strict";

/**
 * Auth benchmarks collector and reporter — same structure as capabilitiesBenchmarks/index.js.
 */

function createBenchmarkCollector() {
  var records = [];

  function recordOp(label, durationMs, metadata) {
    records.push({
      label: label,
      durationMs: durationMs,
      timestamp: Date.now(),
      metadata: metadata || {},
    });
  }

  function getRecords() { return records.slice(); }

  function clear() { records = []; }

  function summary() {
    if (records.length === 0) return { count: 0, totalMs: 0, avgMs: 0, minMs: 0, maxMs: 0 };
    var total = records.reduce(function (a, r) { return a + r.durationMs; }, 0);
    var min = records.reduce(function (a, r) { return Math.min(a, r.durationMs); }, Infinity);
    var max = records.reduce(function (a, r) { return Math.max(a, r.durationMs); }, -Infinity);
    return {
      count: records.length,
      totalMs: total,
      avgMs: total / records.length,
      minMs: min,
      maxMs: max,
    };
  }

  return { recordOp, getRecords, clear, summary };
}

function formatBenchmarkReport(results) {
  var lines = ["", "AUTH BENCHMARK REPORT", "═".repeat(60)];
  for (var i = 0; i < results.length; i++) {
    var r = results[i];
    lines.push("");
    lines.push("  Batch : " + r.label);
    lines.push("  Ops   : " + r.summary.count);
    lines.push("  Total : " + r.summary.totalMs.toFixed(2) + " ms");
    lines.push("  Avg   : " + r.summary.avgMs.toFixed(2) + " ms/op");
    lines.push("  Min   : " + r.summary.minMs.toFixed(2) + " ms");
    lines.push("  Max   : " + r.summary.maxMs.toFixed(2) + " ms");
    if (r.failed > 0) {
      lines.push("  ✗ FAILURES: " + r.failed);
    } else {
      lines.push("  ✓ All ops passed");
    }
    lines.push("  " + "─".repeat(55));
  }
  return lines.join("\n");
}

module.exports = { createBenchmarkCollector, formatBenchmarkReport };
