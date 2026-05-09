"use strict";

/**
 * integrationClient.js — Frontend view-model for integration management.
 * Delegates to an injected integrationAdapter; drives UI via subscribe/notify.
 */

function createIntegrationClient(options) {
  var config = Object.assign(
    {
      adapter: null,  // { connect(id), disconnect(id), getStatus(id), list() }
    },
    options || {}
  );

  var state = {
    loading:      false,
    integrations: new Map(),
    error:        null,
    lastUpdated:  null,
  };

  var listeners = [];

  function notify() {
    var snapshot = getState();
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](snapshot); } catch (_) {}
    }
  }

  function subscribe(fn) {
    listeners.push(fn);
    return function () { listeners = listeners.filter(function (l) { return l !== fn; }); };
  }

  function setLoading(val) { state.loading = val; notify(); }
  function setError(err) { state.error = err; notify(); }

  async function connect(integrationId) {
    setLoading(true);
    setError(null);
    try {
      var adapter = config.adapter;
      var result = adapter ? await adapter.connect(integrationId) : { ok: true, status: "connected" };
      state.integrations.set(integrationId, { id: integrationId, status: (result && result.status) || "connected", connectedAt: Date.now() });
      state.lastUpdated = Date.now();
      setLoading(false);
      return result;
    } catch (err) {
      setError((err && err.message) || "connect failed");
      setLoading(false);
      return { ok: false, error: state.error };
    }
  }

  async function disconnect(integrationId) {
    setLoading(true);
    setError(null);
    try {
      var adapter = config.adapter;
      var result = adapter ? await adapter.disconnect(integrationId) : { ok: true };
      state.integrations.set(integrationId, { id: integrationId, status: "disconnected", disconnectedAt: Date.now() });
      state.lastUpdated = Date.now();
      setLoading(false);
      return result;
    } catch (err) {
      setError((err && err.message) || "disconnect failed");
      setLoading(false);
      return { ok: false, error: state.error };
    }
  }

  async function getStatus(integrationId) {
    try {
      var adapter = config.adapter;
      var result = adapter ? await adapter.getStatus(integrationId) : { ok: true, status: "unknown" };
      if (result && result.status) {
        var existing = state.integrations.get(integrationId) || { id: integrationId };
        existing.status = result.status;
        state.integrations.set(integrationId, existing);
        notify();
      }
      return result;
    } catch (err) {
      return { ok: false, error: (err && err.message) || "getStatus failed" };
    }
  }

  async function listIntegrations() {
    setLoading(true);
    setError(null);
    try {
      var adapter = config.adapter;
      var result = adapter ? await adapter.list() : { ok: true, integrations: [] };
      if (result && result.integrations) {
        result.integrations.forEach(function (item) { state.integrations.set(item.id, item); });
      }
      state.lastUpdated = Date.now();
      setLoading(false);
      return result;
    } catch (err) {
      setError((err && err.message) || "listIntegrations failed");
      setLoading(false);
      return { ok: false, error: state.error };
    }
  }

  function getState() {
    return {
      loading:      state.loading,
      integrations: Array.from(state.integrations.values()),
      error:        state.error,
      lastUpdated:  state.lastUpdated,
    };
  }

  return { connect, disconnect, getStatus, listIntegrations, subscribe, getState };
}

if (typeof module !== "undefined") module.exports = { createIntegrationClient };
