/**
 * mockRetryTool — Fails N times before succeeding
 * Usage: { failCount: 2, delayMs: 10 }
 * Tracks attempts via execution context
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  // Track retry state globally during test
  var retryState = {};

  global.AmiCorMockTools.retryTool = {
    name: "mock-retry",
    description: "Fails N times, then succeeds on attempt N+1",
    schema: {
      failCount: { type: "number", required: true, min: 0, max: 10 },
      delayMs: { type: "number", required: false, min: 0, max: 1000 },
      caseId: { type: "string", required: false }
    },
    permissions: [],
    timeout: 10000,
    retryable: true,
    execute: function (args, ctx) {
      var failCount = args.failCount || 2;
      var delay = args.delayMs || 0;
      var caseId = args.caseId || "default";
      var key = "retry-" + caseId;

      if (!retryState[key]) {
        retryState[key] = 0;
      }
      retryState[key]++;

      return new Promise(function (resolve, reject) {
        var delayFn = delay > 0 ? setTimeout : setImmediate;
        var delayArg = delay > 0 ? delay : undefined;

        var callback = function () {
          if (retryState[key] <= failCount) {
            reject(new Error("Mock retry failure: attempt " + retryState[key] + "/" + (failCount + 1)));
          } else {
            resolve({ retriedTimes: retryState[key] - 1, finalAttempt: retryState[key] });
            delete retryState[key]; // cleanup
          }
        };

        if (delayFn === setTimeout) {
          delayFn(callback, delayArg);
        } else {
          delayFn(callback);
        }
      });
    }
  };

  // Expose state for testing
  global.AmiCorMockTools._retryState = retryState;
})(typeof global !== "undefined" ? global : globalThis);
