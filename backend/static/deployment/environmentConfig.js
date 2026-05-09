"use strict";

/**
 * environmentConfig.js — Environment-aware configuration manager.
 * Reads from a provided env map (defaults to process.env).
 */

const { ENVIRONMENTS } = require("./deploymentSchemas");

function createEnvironmentConfig(options) {
  var config = Object.assign(
    {
      env:     null,       // defaults to process.env; inject for testing
      defaults: {},        // key → default value
    },
    options || {}
  );

  var envSource = config.env || process.env;
  var overrides = {};    // runtime overrides (set at runtime, not from process.env)

  function detect() {
    var node_env = (overrides["NODE_ENV"] || envSource["NODE_ENV"] || "dev").toLowerCase();
    if (node_env === "production" || node_env === "prod") return ENVIRONMENTS.production;
    if (node_env === "staging")                             return ENVIRONMENTS.staging;
    return ENVIRONMENTS.dev;
  }

  function get(key) {
    if (key in overrides) return overrides[key];
    if (key in envSource) return envSource[key];
    if (key in config.defaults) return config.defaults[key];
    return undefined;
  }

  function getRequired(key) {
    var val = get(key);
    if (val === undefined || val === null || val === "") {
      throw new Error("Required config key missing: " + key);
    }
    return val;
  }

  function set(key, value) {
    overrides[key] = value;
    return value;
  }

  function has(key) {
    return get(key) !== undefined;
  }

  function getAll() {
    var result = Object.assign({}, config.defaults);
    // Apply env source (may include sensitive keys — caller's responsibility)
    for (var k in envSource) {
      if (Object.prototype.hasOwnProperty.call(envSource, k)) result[k] = envSource[k];
    }
    // Apply runtime overrides last
    Object.assign(result, overrides);
    return result;
  }

  function getEnvironment() { return detect(); }
  function isDev() { return detect() === ENVIRONMENTS.dev; }
  function isStaging() { return detect() === ENVIRONMENTS.staging; }
  function isProduction() { return detect() === ENVIRONMENTS.production; }

  /**
   * validate(schema) — schema: { required: string[], optional: { key: defaultValue } }
   * Returns { ok, missing: [], invalid: [] }
   */
  function validate(schema) {
    var s = schema || {};
    var missing = [];
    var invalid = [];

    (s.required || []).forEach(function (key) {
      var val = get(key);
      if (val === undefined || val === null || val === "") missing.push(key);
    });

    var optionalDefaults = s.optional || {};
    Object.keys(optionalDefaults).forEach(function (key) {
      if (!has(key)) set(key, optionalDefaults[key]);
    });

    // Type validators: { key: (value) => bool }
    var typeChecks = s.types || {};
    Object.keys(typeChecks).forEach(function (key) {
      if (has(key)) {
        var val = get(key);
        if (!typeChecks[key](val)) invalid.push(key);
      }
    });

    return { ok: missing.length === 0 && invalid.length === 0, missing, invalid };
  }

  return {
    get,
    getRequired,
    set,
    has,
    getAll,
    getEnvironment,
    isDev,
    isStaging,
    isProduction,
    validate,
    ENVIRONMENTS,
  };
}

module.exports = { createEnvironmentConfig };
