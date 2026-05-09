"use strict";

function percentile(sortedValues, ratio) {
  if (!sortedValues.length) {
    return 0;
  }
  var index = Math.min(sortedValues.length - 1, Math.max(0, Math.ceil(sortedValues.length * ratio) - 1));
  return sortedValues[index];
}

function createBenchmarkCollector(label) {
  var startedAt = Date.now();
  var heapStart = process.memoryUsage().heapUsed;
  var latencies = [];
  var completed = 0;
  var failed = 0;

  return {
    recordLatency: function (durationMs) {
      latencies.push(durationMs);
    },
    recordResult: function (status) {
      if (status === "completed") {
        completed += 1;
      } else {
        failed += 1;
      }
    },
    finish: function (operations) {
      var elapsedMs = Math.max(1, Date.now() - startedAt);
      var sorted = latencies.slice().sort(function (a, b) { return a - b; });
      var totalLatency = latencies.reduce(function (sum, value) { return sum + value; }, 0);
      return {
        label: label,
        operationCount: operations || latencies.length,
        elapsedMs: elapsedMs,
        throughputOpsPerSec: Number(((operations || latencies.length) / (elapsedMs / 1000)).toFixed(2)),
        avgLatencyMs: Number((totalLatency / Math.max(1, latencies.length)).toFixed(2)),
        p50LatencyMs: percentile(sorted, 0.5),
        p95LatencyMs: percentile(sorted, 0.95),
        p99LatencyMs: percentile(sorted, 0.99),
        completed: completed,
        failed: failed,
        memoryEstimateBytes: Math.max(0, process.memoryUsage().heapUsed - heapStart),
      };
    },
  };
}

function formatBenchmarkReport(summaries) {
  var lines = [];
  lines.push("\nASSISTANT BENCHMARK REPORT");
  lines.push("────────────────────────────────────────────────────────────");

  for (var i = 0; i < summaries.length; i++) {
    var summary = summaries[i];
    lines.push(summary.label + ":");
    lines.push("  throughput: " + summary.throughputOpsPerSec + " ops/sec");
    lines.push("  completed: " + summary.completed + ", failed: " + summary.failed);
    lines.push("  latency: avg " + summary.avgLatencyMs + "ms, p50 " + summary.p50LatencyMs + "ms, p95 " + summary.p95LatencyMs + "ms, p99 " + summary.p99LatencyMs + "ms");
    lines.push("  memory estimate: " + summary.memoryEstimateBytes + " bytes");
    lines.push("");
  }

  return lines.join("\n");
}

module.exports = {
  createBenchmarkCollector: createBenchmarkCollector,
  formatBenchmarkReport: formatBenchmarkReport,
};
