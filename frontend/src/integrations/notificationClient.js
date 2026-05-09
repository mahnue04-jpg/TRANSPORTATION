"use strict";

/**
 * notificationClient.js — Frontend view-model for in-app notifications.
 */

function createNotificationClient(options) {
  var config = Object.assign(
    {
      adapter:       null,         // { load(userId), markRead(userId, id), markAllRead(userId), delete(userId, id) }
      pollIntervalMs: 0,           // 0 = no polling; positive = auto-refresh interval
    },
    options || {}
  );

  var state = {
    loading:        false,
    notifications:  [],
    unreadCount:    0,
    error:          null,
    userId:         null,
  };

  var listeners = [];
  var pollTimer = null;

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

  function computeUnread() {
    return state.notifications.filter(function (n) { return !n.read; }).length;
  }

  async function load(userId) {
    state.userId = userId;
    state.loading = true;
    state.error = null;
    notify();
    try {
      var adapter = config.adapter;
      var result = adapter
        ? await adapter.load(userId)
        : { ok: true, notifications: [] };
      if (result && result.notifications) {
        state.notifications = result.notifications;
        state.unreadCount = computeUnread();
      }
      state.loading = false;
      notify();
      return result;
    } catch (err) {
      state.error = (err && err.message) || "load failed";
      state.loading = false;
      notify();
      return { ok: false, error: state.error };
    }
  }

  async function markRead(notifId) {
    var adapter = config.adapter;
    try {
      if (adapter) await adapter.markRead(state.userId, notifId);
      state.notifications = state.notifications.map(function (n) {
        if (n.id === notifId) return Object.assign({}, n, { read: true, readAt: Date.now() });
        return n;
      });
      state.unreadCount = computeUnread();
      notify();
      return { ok: true };
    } catch (err) {
      return { ok: false, error: (err && err.message) || "markRead failed" };
    }
  }

  async function markAllRead() {
    var adapter = config.adapter;
    try {
      if (adapter) await adapter.markAllRead(state.userId);
      var now = Date.now();
      state.notifications = state.notifications.map(function (n) {
        return n.read ? n : Object.assign({}, n, { read: true, readAt: now });
      });
      state.unreadCount = 0;
      notify();
      return { ok: true };
    } catch (err) {
      return { ok: false, error: (err && err.message) || "markAllRead failed" };
    }
  }

  async function deleteNotification(notifId) {
    var adapter = config.adapter;
    try {
      if (adapter) await adapter.delete(state.userId, notifId);
      state.notifications = state.notifications.filter(function (n) { return n.id !== notifId; });
      state.unreadCount = computeUnread();
      notify();
      return { ok: true };
    } catch (err) {
      return { ok: false, error: (err && err.message) || "delete failed" };
    }
  }

  function startPolling(userId) {
    stopPolling();
    if (!config.pollIntervalMs) return;
    load(userId || state.userId);
    pollTimer = setInterval(function () { load(userId || state.userId); }, config.pollIntervalMs);
    if (pollTimer.unref) pollTimer.unref();
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function getState() {
    return {
      loading:       state.loading,
      notifications: state.notifications.slice(),
      unreadCount:   state.unreadCount,
      error:         state.error,
      userId:        state.userId,
    };
  }

  return { load, markRead, markAllRead, deleteNotification, startPolling, stopPolling, subscribe, getState };
}

if (typeof module !== "undefined") module.exports = { createNotificationClient };
