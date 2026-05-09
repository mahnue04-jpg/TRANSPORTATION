/**
 * mockTimeoutTool — Will always timeout if duration is too short
 * Usage: { taskDurationMs: 5000 }
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  global.AmiCorMockTools.timeoutTool = {
    name: "mock-timeout",
    description: "Task that may timeout based on timeout setting",
    schema: {
      taskDurationMs: { type: "number", required: true, min: 100, max: 60000 }
    },
    permissions: [],
    timeout: 2000, // Fixed short timeout to trigger timeouts in tests
    retryable: true,
    execute: function (args) {
      var duration = args.taskDurationMs || 5000;
      var startTime = Date.now();

      return new Promise(function (resolve) {
        setTimeout(function () {
          var elapsed = Date.now() - startTime;
          resolve({
            completed: true,
            requestedDurationMs: duration,
            actualDurationMs: elapsed
          });
        }, duration);
      });
    }
  };
})(typeof global !== "undefined" ? global : globalThis);
