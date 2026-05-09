/* ─── runtime/errors.js ──────────────────────────────────────────────────
 * Structured tool-runtime error types (ES5-compatible).
 * Exposed on window._AmiCorRT.errors
 * ─────────────────────────────────────────────────────────────────────── */
(function (global) {
  "use strict";
  var ns = global._AmiCorRT = global._AmiCorRT || {};

  function makeStructuredError(name, defaultRetryable) {
    function StructuredError(message, extra) {
      this.message   = message || name;
      this.name      = name;
      this.retryable = (extra && extra.retryable !== undefined)
        ? !!extra.retryable
        : defaultRetryable;
      this.stack = (new Error(this.message)).stack;
      if (extra) {
        var self = this;
        Object.keys(extra).forEach(function (k) {
          if (k !== "retryable") { self[k] = extra[k]; }
        });
      }
    }
    StructuredError.prototype             = Object.create(Error.prototype);
    StructuredError.prototype.constructor = StructuredError;
    StructuredError.prototype.name        = name;
    return StructuredError;
  }

  var ToolValidationError = makeStructuredError("ToolValidationError", false);
  var ToolTimeoutError    = makeStructuredError("ToolTimeoutError",    true);
  var ToolPermissionError = makeStructuredError("ToolPermissionError", false);
  var ToolCancelledError  = makeStructuredError("ToolCancelledError",  false);
  var ToolExecutionError  = makeStructuredError("ToolExecutionError",  true);

  function isRetryable(err) {
    if (!err) { return false; }
    if (typeof err.retryable === "boolean") { return err.retryable; }
    var nonRetryable = ["ToolValidationError", "ToolPermissionError", "ToolCancelledError"];
    return nonRetryable.indexOf(err.name) === -1;
  }

  ns.errors = {
    ToolValidationError : ToolValidationError,
    ToolTimeoutError    : ToolTimeoutError,
    ToolPermissionError : ToolPermissionError,
    ToolCancelledError  : ToolCancelledError,
    ToolExecutionError  : ToolExecutionError,
    isRetryable         : isRetryable
  };
})(window);
