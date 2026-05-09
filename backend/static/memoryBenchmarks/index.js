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
  var queuePressure = 0;
  var streamingUnits = 0;

  return {
    label: label,
    recordLatency: function (durationMs) {
      latencies.push(durationMs);
    },
    recordQueuePressure: function (pressure) {
      queuePressure = Math.max(queuePressure, pressure || 0);
    },
    recordStreaming: function (units) {
      streamingUnits += units || 0;
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
        memoryEstimateBytes: Math.max(0, process.memoryUsage().heapUsed - heapStart),
        queuePressure: queuePressure,
        streamingThroughputUnitsPerSec: Number((streamingUnits / (elapsedMs / 1000)).toFixed(2)),
      };
    },
  };
}

function formatBenchmarkReport(summaries) {
  var lines = [];
  lines.push("\nMEMORY BENCHMARK REPORT");
  lines.push("────────────────────────────────────────────────────────────");
  summaries.forEach(function (summary) {
    lines.push(summary.label + ":");
    lines.push("  throughput: " + summary.throughputOpsPerSec + " ops/sec");
    lines.push("  latency: avg " + summary.avgLatencyMs + "ms, p50 " + summary.p50LatencyMs + "ms, p95 " + summary.p95LatencyMs + "ms, p99 " + summary.p99LatencyMs + "ms");
    lines.push("  memory estimate: " + summary.memoryEstimateBytes + " bytes");
    lines.push("  queue pressure: " + summary.queuePressure);
    lines.push("  streaming throughput: " + summary.streamingThroughputUnitsPerSec + " units/sec");
    lines.push("");
  });
  return lines.join("\n");
}

module.exports = {
  createBenchmarkCollector: createBenchmarkCollector,
  formatBenchmarkReport: formatBenchmarkReport,
};