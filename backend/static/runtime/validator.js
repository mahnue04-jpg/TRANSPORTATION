/* ─── runtime/validator.js ───────────────────────────────────────────────
 * JSON-schema-lite argument validator.
 * Exposed on window._AmiCorRT.validator
 * ─────────────────────────────────────────────────────────────────────── */
(function (global) {
  "use strict";
  var ns = global._AmiCorRT = global._AmiCorRT || {};
  var errors = ns.errors || {};
  var ToolValidationError = errors.ToolValidationError || Error;

  function typeCheck(value, expected, field) {
    var actual = typeof value;
    if (expected === "array") {
      if (!Array.isArray(value)) { return "Field '" + field + "' must be an array"; }
    } else if (expected === "integer") {
      if (typeof value !== "number" || Math.floor(value) !== value) {
        return "Field '" + field + "' must be an integer";
      }
    } else if (actual !== expected) {
      return "Field '" + field + "' must be of type " + expected + " (got " + actual + ")";
    }
    return null;
  }

  function validateSchema(args, schema) {
    if (!schema || typeof schema !== "object") { return; }
    var required  = schema.required  || [];
    var props     = schema.properties || {};
    var strict    = !!schema.__strict;

    /* Check required fields */
    required.forEach(function (field) {
      if (args[field] === undefined) {
        throw new ToolValidationError("Missing required field: " + field);
      }
    });

    /* Validate each declared property */
    Object.keys(props).forEach(function (field) {
      var rule  = props[field];
      var value = args[field];
      if (value === undefined) { return; }

      if (rule.type) {
        var typeErr = typeCheck(value, rule.type, field);
        if (typeErr) { throw new ToolValidationError(typeErr); }
      }
      if (rule.enum && rule.enum.indexOf(value) === -1) {
        throw new ToolValidationError(
          "Field '" + field + "' must be one of: " + rule.enum.join(", ")
        );
      }
      if (rule.type === "string" || typeof value === "string") {
        if (rule.minLength !== undefined && value.length < rule.minLength) {
          throw new ToolValidationError(
            "Field '" + field + "' must be at least " + rule.minLength + " characters"
          );
        }
        if (rule.maxLength !== undefined && value.length > rule.maxLength) {
          throw new ToolValidationError(
            "Field '" + field + "' must be at most " + rule.maxLength + " characters"
          );
        }
      }
      if (typeof value === "number") {
        if (rule.min !== undefined && value < rule.min) {
          throw new ToolValidationError("Field '" + field + "' must be >= " + rule.min);
        }
        if (rule.max !== undefined && value > rule.max) {
          throw new ToolValidationError("Field '" + field + "' must be <= " + rule.max);
        }
      }
    });

    /* Strict mode: reject undeclared keys */
    if (strict) {
      Object.keys(args).forEach(function (k) {
        if (!props[k]) {
          throw new ToolValidationError("Unknown field in strict mode: " + k);
        }
      });
    }
  }

  ns.validator = { validateSchema: validateSchema };
})(window);
