/**
 * mockFailTool — Always fails with optional custom error
 * Usage: { errorMessage: "Something went wrong" }
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  global.AmiCorMockTools.failTool = {
    name: "mock-fail",
    description: "Always fails with a configurable error message",
    schema: {
      errorMessage: { type: "string", required: false }
    },
    permissions: [],
    timeout: 5000,
    retryable: true,
    execute: function (args) {
      var msg = args.errorMessage || "Mock failure: test error";
      return Promise.reject(new Error(msg));
    }
  };
})(typeof global !== "undefined" ? global : globalThis);
