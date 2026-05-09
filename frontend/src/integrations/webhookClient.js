"use strict";

/**
 * webhookClient.js — Frontend view-model for webhook management.
 */

function createWebhookClient(options) {
  var config = Object.assign(
    {
      adapter: null,  // { register(event, url), unregister(id), list() }
    },
    options || {}
  );

  var state = {
    loading:  false,
    webhooks: [],
    error:    null,
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

  async function register(event, url, metadata) {
    state.loading = true;
    state.error = null;
    notify();
    try {
      var adapter = config.adapter;
      var result = adapter
        ? await adapter.register(event, url, metadata)
        : { ok: true, webhookId: "whk_" + Date.now(), event, url };
      if (result && result.ok !== false) {
        state.webhooks.push({
          id:        result.webhookId || result.id,
          event:     event,
          url:       url,
          active:    true,
          createdAt: Date.now(),
          metadata:  metadata || {},
        });
      }
      state.loading = false;
      notify();
      return result;
    } catch (err) {
      state.error = (err && err.message) || "register failed";
      state.loading = false;
      notify();
      return { ok: false, error: state.error };
    }
  }

  async function unregister(webhookId) {
    state.loading = true;
    state.error = null;
    notify();
    try {
      var adapter = config.adapter;
      var result = adapter ? await adapter.unregister(webhookId) : { ok: true };
      if (result && result.ok !== false) {
        state.webhooks = state.webhooks.filter(function (w) { return w.id !== webhookId; });
      }
      state.loading = false;
      notify();
      return result;
    } catch (err) {
      state.error = (err && err.message) || "unregister failed";
      state.loading = false;
      notify();
      return { ok: false, error: state.error };
    }
  }

  async function listWebhooks() {
    state.loading = true;
    state.error = null;
    notify();
    try {
      var adapter = config.adapter;
      var result = adapter ? await adapter.list() : { ok: true, webhooks: [] };
      if (result && result.webhooks) state.webhooks = result.webhooks;
      state.loading = false;
      notify();
      return result;
    } catch (err) {
      state.error = (err && err.message) || "listWebhooks failed";
      state.loading = false;
      notify();
      return { ok: false, error: state.error };
    }
  }

  function getState() {
    return { loading: state.loading, webhooks: state.webhooks.slice(), error: state.error };
  }

  return { register, unregister, listWebhooks, subscribe, getState };
}

if (typeof module !== "undefined") module.exports = { createWebhookClient };
