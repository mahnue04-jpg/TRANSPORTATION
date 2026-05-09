"use strict";

/**
 * serviceAdapter.js — Base service adapter system.
 * Provides a standard interface for plugging in provider implementations.
 */

const {
  INTEGRATION_STATUS,
  INTEGRATION_ERRORS,
  uid,
  clone,
  createIntegrationError,
  createIntegrationSuccess,
} = require("./integrationSchemas");

/**
 * createServiceAdapter — wraps a provider implementation with standard lifecycle,
 * validation, error normalization, and capability introspection.
 *
 * provider: {
 *   name,
 *   type,
 *   capabilities: string[],
 *   connect(config),
 *   disconnect(),
 *   healthCheck(),
 *   [capability methods]...
 * }
 */
function createServiceAdapter(provider, options) {
  if (!provider || typeof provider !== "object") {
    throw new Error("serviceAdapter: provider must be an object");
  }

  var adapterConfig = Object.assign(
    {
      validateConfig:  null,   // function(config) → { ok, message }
      transformError:  null,   // function(err) → normalized error
      timeoutMs:       30000,
    },
    options || {}
  );

  var state = {
    status:      INTEGRATION_STATUS.pending,
    connectedAt: null,
    lastError:   null,
    callCount:   0,
    errorCount:  0,
  };

  function normalizeError(err) {
    if (adapterConfig.transformError) {
      try { return adapterConfig.transformError(err); } catch (_) {}
    }
    if (err && err.ok === false) return err;
    return createIntegrationError(
      INTEGRATION_ERRORS.providerError,
      (err && err.message) || String(err)
    );
  }

  async function connect(config) {
    if (adapterConfig.validateConfig) {
      var validation = adapterConfig.validateConfig(config);
      if (validation && validation.ok === false) {
        return createIntegrationError(INTEGRATION_ERRORS.invalidConfig, validation.message);
      }
    }

    if (typeof provider.connect !== "function") {
      state.status = INTEGRATION_STATUS.connected;
      state.connectedAt = Date.now();
      return createIntegrationSuccess({ status: state.status });
    }

    try {
      var result = await provider.connect(config);
      if (result && result.ok === false) {
        state.status = INTEGRATION_STATUS.error;
        state.lastError = result.message;
        return normalizeError(result);
      }
      state.status = INTEGRATION_STATUS.connected;
      state.connectedAt = Date.now();
      state.lastError = null;
      return createIntegrationSuccess({ status: state.status });
    } catch (err) {
      state.status = INTEGRATION_STATUS.error;
      state.lastError = (err && err.message) || "connect failed";
      return normalizeError(err);
    }
  }

  async function disconnect() {
    if (typeof provider.disconnect === "function") {
      try { await provider.disconnect(); } catch (_) {}
    }
    state.status = INTEGRATION_STATUS.disconnected;
    return createIntegrationSuccess({ status: state.status });
  }

  async function healthCheck() {
    if (typeof provider.healthCheck !== "function") {
      return createIntegrationSuccess({ healthy: state.status === INTEGRATION_STATUS.connected });
    }
    try {
      var result = await provider.healthCheck();
      var healthy = !result || result.ok !== false;
      state.status = healthy ? INTEGRATION_STATUS.connected : INTEGRATION_STATUS.degraded;
      return createIntegrationSuccess({ healthy, status: state.status });
    } catch (err) {
      state.status = INTEGRATION_STATUS.degraded;
      state.lastError = (err && err.message) || "health check failed";
      return createIntegrationSuccess({ healthy: false, status: state.status, error: state.lastError });
    }
  }

  /**
   * call(capability, ...args) — delegates to provider[capability](...args)
   * with error normalization and telemetry tracking.
   */
  async function call(capability) {
    var args = Array.prototype.slice.call(arguments, 1);
    state.callCount += 1;

    if (state.status !== INTEGRATION_STATUS.connected) {
      state.errorCount += 1;
      return createIntegrationError(
        INTEGRATION_ERRORS.notConnected,
        "Adapter is not connected (status: " + state.status + ")"
      );
    }

    if (!hasCapability(capability)) {
      state.errorCount += 1;
      return createIntegrationError(
        INTEGRATION_ERRORS.notFound,
        "Provider does not support capability: " + capability
      );
    }

    try {
      var result = await provider[capability].apply(provider, args);
      return result;
    } catch (err) {
      state.errorCount += 1;
      state.lastError = (err && err.message) || "call failed";
      return normalizeError(err);
    }
  }

  function hasCapability(cap) {
    if (provider.capabilities && Array.isArray(provider.capabilities)) {
      return provider.capabilities.indexOf(cap) !== -1;
    }
    return typeof provider[cap] === "function";
  }

  function listCapabilities() {
    if (provider.capabilities) return provider.capabilities.slice();
    return Object.keys(provider).filter(function (k) { return typeof provider[k] === "function" && k !== "connect" && k !== "disconnect" && k !== "healthCheck"; });
  }

  function getState() { return Object.assign({}, state); }

  return {
    name:             provider.name || "unknown",
    type:             provider.type || "custom",
    connect:          connect,
    disconnect:       disconnect,
    healthCheck:      healthCheck,
    call:             call,
    hasCapability:    hasCapability,
    listCapabilities: listCapabilities,
    getState:         getState,
  };
}

/**
 * createMockProvider — utility to create test/mock providers.
 */
function createMockProvider(overrides) {
  var opts = overrides || {};
  return Object.assign(
    {
      name:         "mock",
      type:         "custom",
      capabilities: opts.capabilities || [],
      connect:      async function () { return { ok: true }; },
      disconnect:   async function () {},
      healthCheck:  async function () { return { ok: true }; },
    },
    opts
  );
}

module.exports = { createServiceAdapter, createMockProvider };
