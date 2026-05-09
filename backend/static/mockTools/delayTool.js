/**
 * mockDelayTool — Introduces configurable delays for timing tests
 * Usage: { delayMs: 100 }
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  global.AmiCorMockTools.delayTool = {
    name: "mock-delay",
    description: "Introduces a delay before returning success",
    schema: {
      delayMs: { type: "number", required: true, min: 0, max: 60000 }
    },
    permissions: [],
    timeout: 65000,
    retryable: false,
    execute: function (args) {
      return new Promise(function (resolve) {
        setTimeout(function () {
          resolve({ delayed: true, durationMs: args.delayMs });
        }, args.delayMs);
      });
    }
  };
})(typeof global !== "undefined" ? global : globalThis);
