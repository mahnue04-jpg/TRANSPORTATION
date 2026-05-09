"use strict";

/**
 * webhookSystem.js — Webhook/event registration, dispatch, retry, and delivery tracking.
 */

const {
  WEBHOOK_EVENTS,
  INTEGRATION_ERRORS,
  uid,
  clone,
  createWebhookRecord,
  createIntegrationError,
  createIntegrationSuccess,
} = require("./integrationSchemas");

const crypto = require("crypto");

function createWebhookSystem(options) {
  var config = Object.assign(
    {
      maxRetries:      3,
      retryDelayMs:    1000,
      retryBackoff:    2,
      signatureHeader: "X-Amicore-Signature",
      maxWebhooksPerIntegration: 20,
      deliver:         null,  // async function(webhook, payload) → { ok }; if null, simulates delivery
    },
    options || {}
  );

  // webhookId → record
  var webhooks = new Map();
  // integrationId → Set(webhookId)
  var integrationIndex = new Map();
  // delivery log: webhookId → [delivery records]
  var deliveryLog = new Map();
  // event → [handlers]
  var listeners = {};

  function emit(event, data) {
    var handlers = listeners[event] || [];
    for (var i = 0; i < handlers.length; i++) { try { handlers[i](data); } catch (_) {} }
  }

  function on(event, handler) {
    if (!listeners[event]) listeners[event] = [];
    listeners[event].push(handler);
    return function () {
      listeners[event] = (listeners[event] || []).filter(function (h) { return h !== handler; });
    };
  }

  /**
   * Register a webhook for an integration event.
   */
  function register(options) {
    var opts = options || {};
    var integrationId = opts.integrationId || uid("int");

    var existing = integrationIndex.get(integrationId);
    if (existing && existing.size >= config.maxWebhooksPerIntegration) {
      return createIntegrationError(
        INTEGRATION_ERRORS.invalidConfig,
        "Max webhooks per integration reached (" + config.maxWebhooksPerIntegration + ")"
      );
    }

    var record = createWebhookRecord({
      id:            opts.id || uid("whk"),
      integrationId: integrationId,
      event:         opts.event || WEBHOOK_EVENTS.triggered,
      url:           opts.url || null,
      secret:        opts.secret || null,
      metadata:      opts.metadata || {},
    });

    webhooks.set(record.id, record);

    if (!integrationIndex.has(integrationId)) integrationIndex.set(integrationId, new Set());
    integrationIndex.get(integrationId).add(record.id);

    if (!deliveryLog.has(record.id)) deliveryLog.set(record.id, []);

    emit("registered", clone(record));
    return createIntegrationSuccess({ webhookId: record.id, webhook: clone(record) });
  }

  /**
   * Compute HMAC-SHA256 signature for payload.
   */
  function signPayload(secret, payload) {
    if (!secret) return null;
    var str = typeof payload === "string" ? payload : JSON.stringify(payload);
    return "sha256=" + crypto.createHmac("sha256", secret).update(str).digest("hex");
  }

  /**
   * Deliver a webhook with retry on failure.
   */
  async function deliver(webhookId, payload) {
    var record = webhooks.get(webhookId);
    if (!record) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Webhook not found: " + webhookId);
    if (!record.active) return createIntegrationError(INTEGRATION_ERRORS.invalidConfig, "Webhook is inactive");

    var deliveryId = uid("dlv");
    var payloadStr = typeof payload === "string" ? payload : JSON.stringify(payload);
    var signature = signPayload(record.secret, payloadStr);

    var attempt = 0;
    var maxAttempts = config.maxRetries + 1;
    var delay = config.retryDelayMs;

    while (attempt < maxAttempts) {
      var start = Date.now();
      try {
        var deliverFn = config.deliver;
        var result;

        if (typeof deliverFn === "function") {
          result = await deliverFn(
            { id: record.id, url: record.url, signature, signatureHeader: config.signatureHeader },
            payload
          );
        } else {
          // Simulated delivery (for tests/offline mode)
          result = { ok: true, status: 200 };
        }

        var elapsed = Date.now() - start;
        var logEntry = {
          deliveryId,
          webhookId,
          attempt,
          durationMs: elapsed,
          ok: result && result.ok !== false,
          status: result && result.status,
          timestamp: Date.now(),
        };

        var log = deliveryLog.get(webhookId) || [];
        log.push(logEntry);
        deliveryLog.set(webhookId, log);

        if (logEntry.ok) {
          record.deliveredAt = Date.now();
          record.failCount = 0;
          emit("delivered", { webhookId, deliveryId, attempt });
          return createIntegrationSuccess({ webhookId, deliveryId, attempt });
        }

        // Non-exception failure (bad status)
        record.failCount += 1;
        attempt += 1;
        if (attempt < maxAttempts) {
          await new Promise(function (r) { setTimeout(r, delay); });
          delay = Math.min(delay * config.retryBackoff, 10000);
        }
      } catch (err) {
        record.failCount += 1;
        attempt += 1;
        if (attempt < maxAttempts) {
          emit("retrying", { webhookId, attempt, error: (err && err.message) || String(err) });
          await new Promise(function (r) { setTimeout(r, delay); });
          delay = Math.min(delay * config.retryBackoff, 10000);
        }
      }
    }

    emit("failed", { webhookId, deliveryId });
    return createIntegrationError(INTEGRATION_ERRORS.webhookFailed, "Webhook delivery failed after " + config.maxRetries + " retries");
  }

  /**
   * Dispatch an event to all matching webhooks for an integration.
   */
  async function dispatch(integrationId, event, payload) {
    var ids = integrationIndex.get(integrationId);
    if (!ids || ids.size === 0) return createIntegrationSuccess({ dispatched: 0 });

    var results = [];
    for (var wid of ids) {
      var record = webhooks.get(wid);
      if (!record || !record.active) continue;
      if (record.event !== event && record.event !== "*") continue;
      results.push(deliver(wid, payload));
    }

    var settled = await Promise.all(results);
    var failed = settled.filter(function (r) { return !r.ok; }).length;
    return createIntegrationSuccess({ dispatched: settled.length, failed });
  }

  function getWebhook(webhookId) {
    var r = webhooks.get(webhookId);
    return r ? clone(r) : null;
  }

  function listWebhooks(integrationId) {
    var ids = integrationIndex.get(integrationId);
    if (!ids) return [];
    var list = [];
    for (var id of ids) {
      var r = webhooks.get(id);
      if (r) list.push(clone(r));
    }
    return list;
  }

  function deactivate(webhookId) {
    var r = webhooks.get(webhookId);
    if (!r) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Webhook not found: " + webhookId);
    r.active = false;
    return createIntegrationSuccess({ webhookId });
  }

  function getDeliveryLog(webhookId) {
    return (deliveryLog.get(webhookId) || []).slice();
  }

  function webhookCount() { return webhooks.size; }

  return {
    register,
    deliver,
    dispatch,
    deactivate,
    getWebhook,
    listWebhooks,
    getDeliveryLog,
    webhookCount,
    on,
    signPayload,
  };
}

module.exports = { createWebhookSystem };
