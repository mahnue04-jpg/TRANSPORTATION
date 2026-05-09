"use strict";

function percentile(sortedValues, ratio) {
  if (!sortedValues.length) {
    return 0;
  }
  const index = Math.min(sortedValues.length - 1, Math.max(0, Math.ceil(sortedValues.length * ratio) - 1));
  return sortedValues[index];
}

function createBenchmarkCollector(label) {
  const startedAt = Date.now();
  const heapStart = process.memoryUsage().heapUsed;
  const latencies = [];
  let maxQueuePressure = 0;
  let streamChunks = 0;
  let streamBytes = 0;

  return {
    label: label,
    recordLatency: function (durationMs) {
      latencies.push(durationMs);
    },
    recordQueuePressure: function (pressure) {
      maxQueuePressure = Math.max(maxQueuePressure, pressure || 0);
    },
    recordStreaming: function (chunks, bytes) {
      streamChunks += chunks || 0;
      streamBytes += bytes || 0;
    },
    finish: function (operationCount) {
      const elapsedMs = Math.max(1, Date.now() - startedAt);
      const sorted = latencies.slice().sort(function (a, b) { return a - b; });
      const totalLatency = latencies.reduce(function (sum, value) { return sum + value; }, 0);
      const memoryEstimate = Math.max(0, process.memoryUsage().heapUsed - heapStart);

      return {
        label: label,
        operationCount: operationCount || latencies.length,
        elapsedMs: elapsedMs,
        throughputOpsPerSec: Number(((operationCount || latencies.length) / (elapsedMs / 1000)).toFixed(2)),
        avgLatencyMs: Number((totalLatency / Math.max(1, latencies.length)).toFixed(2)),
        p50LatencyMs: percentile(sorted, 0.5),
        p95LatencyMs: percentile(sorted, 0.95),
        p99LatencyMs: percentile(sorted, 0.99),
        memoryEstimateBytes: memoryEstimate,
        maxQueuePressure: maxQueuePressure,
        streamingThroughputChunksPerSec: Number((streamChunks / (elapsedMs / 1000)).toFixed(2)),
        streamingThroughputBytesPerSec: Number((streamBytes / (elapsedMs / 1000)).toFixed(2)),
      };
    },
  };
}

function formatBenchmarkReport(summaryList) {
  const lines = [];
  lines.push("\nBENCHMARK REPORT");
  lines.push("────────────────────────────────────────────────────────────");
  summaryList.forEach(function (summary) {
    lines.push(summary.label + ":");
    lines.push("  throughput: " + summary.throughputOpsPerSec + " ops/sec");
    lines.push("  latency: avg " + summary.avgLatencyMs + "ms, p50 " + summary.p50LatencyMs + "ms, p95 " + summary.p95LatencyMs + "ms, p99 " + summary.p99LatencyMs + "ms");
    lines.push("  memory estimate: " + summary.memoryEstimateBytes + " bytes");
    lines.push("  queue pressure: " + summary.maxQueuePressure);
    lines.push("  streaming throughput: " + summary.streamingThroughputChunksPerSec + " chunks/sec, " + summary.streamingThroughputBytesPerSec + " bytes/sec");
    lines.push("");
  });
  return lines.join("\n");
}

module.exports = {
  createBenchmarkCollector: createBenchmarkCollector,
  formatBenchmarkReport: formatBenchmarkReport,
};