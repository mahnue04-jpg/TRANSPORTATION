"use strict";

/**
 * integrationManager.js — Registry and lifecycle manager for all integrations.
 * Supports register, connect, disconnect, health-check and event emission.
 */

const {
  INTEGRATION_STATUS,
  INTEGRATION_ERRORS,
  uid,
  clone,
  createIntegrationRecord,
  createIntegrationError,
  createIntegrationSuccess,
} = require("./integrationSchemas");

function createIntegrationManager(options) {
  var config = Object.assign(
    {
      healthCheckIntervalMs: 0,  // 0 = no auto health check
      maxRetries: 3,
    },
    options || {}
  );

  // integrationId → record
  var integrations = new Map();
  // integrationId → adapter (implements connect/disconnect/healthCheck)
  var adapters = new Map();
  // event listeners: event → [handlers]
  var listeners = {};

  function emit(event, data) {
    var handlers = listeners[event] || [];
    for (var i = 0; i < handlers.length; i++) {
      try { handlers[i](data); } catch (_) {}
    }
    var wildHandlers = listeners["*"] || [];
    for (var j = 0; j < wildHandlers.length; j++) {
      try { wildHandlers[j](event, data); } catch (_) {}
    }
  }

  function on(event, handler) {
    if (!listeners[event]) listeners[event] = [];
    listeners[event].push(handler);
    return function () {
      listeners[event] = (listeners[event] || []).filter(function (h) { return h !== handler; });
    };
  }

  /**
   * Register an integration with an adapter.
   * adapter: { connect(config), disconnect(), healthCheck(), [name], [type] }
   */
  function register(adapterOrOptions, adapterImpl) {
    var opts, adapter;
    if (typeof adapterOrOptions === "object" && adapterImpl) {
      opts = adapterOrOptions;
      adapter = adapterImpl;
    } else {
      opts = adapterOrOptions || {};
      adapter = opts.adapter || null;
    }

    var id = opts.id || uid("int");
    if (integrations.has(id)) {
      return createIntegrationError(INTEGRATION_ERRORS.alreadyRegistered, "Integration already registered: " + id);
    }

    var record = createIntegrationRecord({
      id:       id,
      name:     opts.name || (adapter && adapter.name) || id,
      type:     opts.type || (adapter && adapter.type) || "custom",
      config:   opts.config || {},
      userId:   opts.userId || null,
      metadata: opts.metadata || {},
    });

    integrations.set(id, record);
    if (adapter) adapters.set(id, adapter);

    emit("registered", clone(record));
    return createIntegrationSuccess({ integrationId: id, integration: clone(record) });
  }

  async function connect(integrationId) {
    var record = integrations.get(integrationId);
    if (!record) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Integration not found: " + integrationId);

    var adapter = adapters.get(integrationId);
    if (!adapter || typeof adapter.connect !== "function") {
      record.status = INTEGRATION_STATUS.connected;
      record.connectedAt = Date.now();
      record.updatedAt = Date.now();
      emit("connected", clone(record));
      return createIntegrationSuccess({ integrationId, status: record.status });
    }

    try {
      var result = await adapter.connect(record.config);
      if (result && result.ok === false) {
        record.status = INTEGRATION_STATUS.error;
        record.lastError = result.message || "connect failed";
        record.lastErrorAt = Date.now();
        record.updatedAt = Date.now();
        emit("error", { integrationId, error: record.lastError });
        return createIntegrationError(INTEGRATION_ERRORS.requestFailed, record.lastError);
      }
      record.status = INTEGRATION_STATUS.connected;
      record.connectedAt = Date.now();
      record.updatedAt = Date.now();
      record.lastError = null;
      emit("connected", clone(record));
      return createIntegrationSuccess({ integrationId, status: record.status });
    } catch (err) {
      record.status = INTEGRATION_STATUS.error;
      record.lastError = (err && err.message) || "connect error";
      record.lastErrorAt = Date.now();
      record.updatedAt = Date.now();
      emit("error", { integrationId, error: record.lastError });
      return createIntegrationError(INTEGRATION_ERRORS.requestFailed, record.lastError);
    }
  }

  async function disconnect(integrationId) {
    var record = integrations.get(integrationId);
    if (!record) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Integration not found: " + integrationId);

    var adapter = adapters.get(integrationId);
    if (adapter && typeof adapter.disconnect === "function") {
      try { await adapter.disconnect(); } catch (_) {}
    }

    record.status = INTEGRATION_STATUS.disconnected;
    record.updatedAt = Date.now();
    emit("disconnected", clone(record));
    return createIntegrationSuccess({ integrationId, status: record.status });
  }

  async function healthCheck(integrationId) {
    var record = integrations.get(integrationId);
    if (!record) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Integration not found: " + integrationId);

    var adapter = adapters.get(integrationId);
    if (!adapter || typeof adapter.healthCheck !== "function") {
      return createIntegrationSuccess({ integrationId, healthy: record.status === INTEGRATION_STATUS.connected });
    }

    try {
      var result = await adapter.healthCheck();
      var healthy = result && result.ok !== false;
      record.status = healthy ? INTEGRATION_STATUS.connected : INTEGRATION_STATUS.degraded;
      record.updatedAt = Date.now();
      if (!healthy) {
        record.lastError = (result && result.message) || "health check failed";
        record.lastErrorAt = Date.now();
      }
      return createIntegrationSuccess({ integrationId, healthy, status: record.status });
    } catch (err) {
      record.status = INTEGRATION_STATUS.degraded;
      record.lastError = (err && err.message) || "health check error";
      record.lastErrorAt = Date.now();
      record.updatedAt = Date.now();
      return createIntegrationSuccess({ integrationId, healthy: false, status: record.status, error: record.lastError });
    }
  }

  async function healthCheckAll() {
    var results = {};
    for (var id of integrations.keys()) {
      results[id] = await healthCheck(id);
    }
    return results;
  }

  function getIntegration(integrationId) {
    var r = integrations.get(integrationId);
    return r ? clone(r) : null;
  }

  function listIntegrations(filter) {
    var list = [];
    for (var r of integrations.values()) {
      if (!filter || r.type === filter.type || r.userId === filter.userId || r.status === filter.status) {
        list.push(clone(r));
      }
    }
    return list;
  }

  function unregister(integrationId) {
    if (!integrations.has(integrationId)) {
      return createIntegrationError(INTEGRATION_ERRORS.notFound, "Integration not found: " + integrationId);
    }
    integrations.delete(integrationId);
    adapters.delete(integrationId);
    emit("unregistered", { integrationId });
    return createIntegrationSuccess({ integrationId });
  }

  function integrationCount() { return integrations.size; }

  return {
    register,
    connect,
    disconnect,
    healthCheck,
    healthCheckAll,
    getIntegration,
    listIntegrations,
    unregister,
    integrationCount,
    on,
  };
}

module.exports = { createIntegrationManager };
