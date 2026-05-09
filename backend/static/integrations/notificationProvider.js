"use strict";

/**
 * notificationProvider.js — In-app notification provider.
 * Supports priorities, read tracking, per-user queues.
 */

const {
  INTEGRATION_TYPES,
  INTEGRATION_ERRORS,
  uid,
  clone,
  createIntegrationError,
  createIntegrationSuccess,
} = require("./integrationSchemas");

const NOTIFICATION_TYPES = {
  info:    "info",
  success: "success",
  warning: "warning",
  error:   "error",
  system:  "system",
  workflow: "workflow",
};

const PRIORITY = {
  low:    1,
  normal: 2,
  high:   3,
  urgent: 4,
};

function createNotificationRecord(options) {
  var opts = options || {};
  return {
    id:        opts.id || uid("notif"),
    userId:    opts.userId,
    type:      opts.type || NOTIFICATION_TYPES.info,
    title:     opts.title || "",
    message:   opts.message || "",
    priority:  opts.priority || PRIORITY.normal,
    read:      false,
    readAt:    null,
    data:      clone(opts.data || {}),
    metadata:  clone(opts.metadata || {}),
    createdAt: Date.now(),
    expiresAt: opts.expiresAt || null,
  };
}

function createNotificationProvider(options) {
  var config = Object.assign(
    {
      maxPerUser:  500,
      provider:    null,  // optional external adapter: { send(notification) }
    },
    options || {}
  );

  // userId → [notificationRecord]
  var userQueues = new Map();
  // Event listeners
  var listeners = {};

  function emit(event, data) {
    var hs = listeners[event] || [];
    for (var i = 0; i < hs.length; i++) { try { hs[i](data); } catch (_) {} }
  }

  function on(event, handler) {
    if (!listeners[event]) listeners[event] = [];
    listeners[event].push(handler);
    return function () {
      listeners[event] = (listeners[event] || []).filter(function (h) { return h !== handler; });
    };
  }

  function getUserQueue(userId) {
    if (!userQueues.has(userId)) userQueues.set(userId, []);
    return userQueues.get(userId);
  }

  async function send(options) {
    var opts = options || {};
    if (!opts.userId) return createIntegrationError(INTEGRATION_ERRORS.invalidConfig, "userId is required");
    if (!opts.message && !opts.title) return createIntegrationError(INTEGRATION_ERRORS.invalidConfig, "title or message is required");

    // Optionally forward to external provider
    if (config.provider) {
      try {
        var result = await config.provider.send(opts);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.providerError, result.message);
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "send failed");
      }
    }

    var queue = getUserQueue(opts.userId);

    // Evict oldest non-urgent if at max capacity
    if (queue.length >= config.maxPerUser) {
      var evictIdx = queue.findIndex(function (n) { return n.priority < PRIORITY.urgent; });
      if (evictIdx !== -1) queue.splice(evictIdx, 1);
      else queue.shift();
    }

    var notif = createNotificationRecord(opts);
    queue.push(notif);

    emit("sent", { userId: opts.userId, notifId: notif.id });
    return createIntegrationSuccess({ notification: clone(notif) });
  }

  function markRead(userId, notifId) {
    var queue = getUserQueue(userId);
    var notif = queue.find(function (n) { return n.id === notifId; });
    if (!notif) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Notification not found: " + notifId);
    notif.read = true;
    notif.readAt = Date.now();
    emit("read", { userId, notifId });
    return createIntegrationSuccess({ notifId });
  }

  function markAllRead(userId) {
    var queue = getUserQueue(userId);
    var now = Date.now();
    var count = 0;
    queue.forEach(function (n) {
      if (!n.read) { n.read = true; n.readAt = now; count++; }
    });
    return createIntegrationSuccess({ marked: count });
  }

  function listNotifications(userId, filters) {
    var queue = getUserQueue(userId);
    var opts = filters || {};
    var now = Date.now();

    // Filter out expired
    var visible = queue.filter(function (n) { return !n.expiresAt || n.expiresAt > now; });

    if (opts.unreadOnly) visible = visible.filter(function (n) { return !n.read; });
    if (opts.type) visible = visible.filter(function (n) { return n.type === opts.type; });
    if (opts.minPriority) visible = visible.filter(function (n) { return n.priority >= opts.minPriority; });

    visible.sort(function (a, b) {
      if (b.priority !== a.priority) return b.priority - a.priority;
      return b.createdAt - a.createdAt;
    });

    return createIntegrationSuccess({ notifications: visible.map(clone) });
  }

  function unreadCount(userId) {
    var queue = getUserQueue(userId);
    var now = Date.now();
    var count = queue.filter(function (n) { return !n.read && (!n.expiresAt || n.expiresAt > now); }).length;
    return createIntegrationSuccess({ count });
  }

  function deleteNotification(userId, notifId) {
    var queue = getUserQueue(userId);
    var idx = queue.findIndex(function (n) { return n.id === notifId; });
    if (idx === -1) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Notification not found: " + notifId);
    queue.splice(idx, 1);
    return createIntegrationSuccess({ notifId });
  }

  function clearNotifications(userId) {
    userQueues.set(userId, []);
    return createIntegrationSuccess({ userId });
  }

  function healthCheck() {
    return createIntegrationSuccess({ healthy: true, queueCount: userQueues.size });
  }

  return {
    name:         "notification",
    type:         INTEGRATION_TYPES.notification,
    capabilities: ["send", "markRead", "markAllRead", "listNotifications", "unreadCount", "deleteNotification"],
    NOTIFICATION_TYPES,
    PRIORITY,
    send,
    markRead,
    markAllRead,
    listNotifications,
    unreadCount,
    deleteNotification,
    clearNotifications,
    healthCheck,
    on,
  };
}

module.exports = { createNotificationProvider, NOTIFICATION_TYPES, PRIORITY };
