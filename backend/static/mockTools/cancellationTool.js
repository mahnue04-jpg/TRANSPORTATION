/**
 * mockCancellationTool — Can be cancelled mid-execution
 * Usage: { duration: 5000 }
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  global.AmiCorMockTools.cancellationTool = {
    name: "mock-cancellation",
    description: "Long-running task suitable for cancellation testing",
    schema: {
      duration: { type: "number", required: false, min: 100, max: 60000 }
    },
    permissions: [],
    timeout: 65000,
    retryable: false,
    execute: function (args, ctx) {
      var duration = args.duration || 5000;
      var startTime = Date.now();

      return new Promise(function (resolve, reject) {
        var cancelled = false;

        // Simulate long-running work with periodic checks
        var checkInterval = setInterval(function () {
          if (ctx.isCancelled()) {
            cancelled = true;
            clearInterval(checkInterval);
            reject(new Error("Task was cancelled"));
            return;
          }
          var elapsed = Date.now() - startTime;
          if (elapsed >= duration) {
            clearInterval(checkInterval);
            resolve({
              completed: true,
              durationMs: elapsed,
              wasCancelled: false
            });
          }
        }, 100);

        // Fallback timeout
        setTimeout(function () {
          clearInterval(checkInterval);
          if (!cancelled) {
            resolve({
              completed: true,
              durationMs: Date.now() - startTime,
              wasCancelled: false
            });
          }
        }, duration + 100);
      });
    }
  };
})(typeof global !== "undefined" ? global : globalThis);
