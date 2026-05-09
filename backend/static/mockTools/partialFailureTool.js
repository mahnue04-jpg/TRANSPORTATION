/**
 * mockPartialFailureTool — Random failures to test partial failure scenarios
 * Usage: { failureRate: 0.3 (30%) }
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  global.AmiCorMockTools.partialFailureTool = {
    name: "mock-partial-failure",
    description: "Fails randomly based on failure rate for chaos testing",
    schema: {
      failureRate: { type: "number", required: true, min: 0, max: 1 }
    },
    permissions: [],
    timeout: 5000,
    retryable: true,
    execute: function (args) {
      var failureRate = args.failureRate || 0.5;
      var shouldFail = Math.random() < failureRate;

      return new Promise(function (resolve, reject) {
        setTimeout(function () {
          if (shouldFail) {
            reject(new Error("Random failure: rate=" + (failureRate * 100).toFixed(1) + "%"));
          } else {
            resolve({
              succeeded: true,
              failureRate: failureRate,
              wasSpared: true
            });
          }
        }, Math.random() * 50); // Random execution time 0-50ms
      });
    }
  };
})(typeof global !== "undefined" ? global : globalThis);
