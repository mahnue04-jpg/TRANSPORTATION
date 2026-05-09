/**
 * mockConcurrentTool — Suitable for running in high concurrency
 * Usage: { workId: "work-1", durationMs: 50 }
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  global.AmiCorMockTools.concurrentTool = {
    name: "mock-concurrent",
    description: "Fast tool suitable for high-concurrency stress testing",
    schema: {
      workId: { type: "string", required: true },
      durationMs: { type: "number", required: false, min: 1, max: 5000 }
    },
    permissions: [],
    timeout: 10000,
    retryable: false,
    execute: function (args) {
      var workId = args.workId || "unknown";
      var duration = args.durationMs || 10;
      var startTime = Date.now();

      return new Promise(function (resolve) {
        setTimeout(function () {
          var elapsed = Date.now() - startTime;
          resolve({
            workId: workId,
            completed: true,
            elapsedMs: elapsed,
            requestedDurationMs: duration
          });
        }, duration);
      });
    }
  };
})(typeof global !== "undefined" ? global : globalThis);
