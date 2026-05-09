"use strict";

/**
 * integrationSchemas.js — Shared enums, factory functions, and error codes
 * for the integrations layer.
 */

// ─── Status Enums ──────────────────────────────────────────────────────────────

const INTEGRATION_STATUS = {
  pending:      "pending",
  connected:    "connected",
  degraded:     "degraded",
  disconnected: "disconnected",
  error:        "error",
};

const INTEGRATION_TYPES = {
  email:        "email",
  calendar:     "calendar",
  document:     "document",
  notification: "notification",
  custom:       "custom",
};

const CONNECTOR_METHODS = {
  get:    "GET",
  post:   "POST",
  put:    "PUT",
  patch:  "PATCH",
  delete: "DELETE",
};

const WEBHOOK_EVENTS = {
  created:   "created",
  updated:   "updated",
  deleted:   "deleted",
  triggered: "triggered",
  failed:    "failed",
  retrying:  "retrying",
};

const INTEGRATION_ERRORS = {
  notFound:          "integration_not_found",
  alreadyRegistered: "integration_already_registered",
  notConnected:      "integration_not_connected",
  authFailed:        "integration_auth_failed",
  requestFailed:     "integration_request_failed",
  timeout:           "integration_timeout",
  rateLimited:       "integration_rate_limited",
  invalidConfig:     "integration_invalid_config",
  webhookFailed:     "webhook_failed",
  secretMissing:     "secret_missing",
  networkError:      "network_error",
  providerError:     "provider_error",
};

// ─── ID Generator ─────────────────────────────────────────────────────────────

function uid(prefix) {
  return String(prefix || "id") + "-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
}

// ─── Shallow Clone ────────────────────────────────────────────────────────────

function clone(value) {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map(clone);
  if (typeof value === "object") {
    var out = {};
    var keys = Object.keys(value);
    for (var i = 0; i < keys.length; i++) { out[keys[i]] = clone(value[keys[i]]); }
    return out;
  }
  return value;
}

// ─── Factory Functions ────────────────────────────────────────────────────────

function createIntegrationRecord(options) {
  var opts = options || {};
  return {
    id:          opts.id || uid("int"),
    name:        opts.name || "",
    type:        opts.type || INTEGRATION_TYPES.custom,
    status:      INTEGRATION_STATUS.pending,
    config:      clone(opts.config || {}),
    userId:      opts.userId || null,
    createdAt:   Date.now(),
    updatedAt:   Date.now(),
    connectedAt: null,
    lastErrorAt: null,
    lastError:   null,
    metadata:    clone(opts.metadata || {}),
  };
}

function createWebhookRecord(options) {
  var opts = options || {};
  return {
    id:          opts.id || uid("whk"),
    integrationId: opts.integrationId || null,
    event:       opts.event || WEBHOOK_EVENTS.triggered,
    url:         opts.url || null,
    secret:      opts.secret || null,
    active:      true,
    createdAt:   Date.now(),
    deliveredAt: null,
    failCount:   0,
    metadata:    clone(opts.metadata || {}),
  };
}

function createApiRequest(options) {
  var opts = options || {};
  return {
    id:          opts.id || uid("req"),
    method:      opts.method || CONNECTOR_METHODS.get,
    url:         opts.url || "",
    headers:     clone(opts.headers || {}),
    body:        opts.body !== undefined ? opts.body : null,
    timeout:     opts.timeout || 30000,
    retries:     opts.retries || 0,
    createdAt:   Date.now(),
  };
}

function createApiResponse(options) {
  var opts = options || {};
  return {
    ok:         opts.ok !== undefined ? opts.ok : false,
    status:     opts.status || 0,
    body:       opts.body !== undefined ? opts.body : null,
    headers:    clone(opts.headers || {}),
    error:      opts.error || null,
    durationMs: opts.durationMs || 0,
    requestId:  opts.requestId || null,
    retries:    opts.retries || 0,
  };
}

function createIntegrationError(code, message, meta) {
  return { ok: false, error: code, message: message || code, meta: meta || {} };
}

function createIntegrationSuccess(data) {
  return Object.assign({ ok: true }, data || {});
}

module.exports = {
  INTEGRATION_STATUS,
  INTEGRATION_TYPES,
  CONNECTOR_METHODS,
  WEBHOOK_EVENTS,
  INTEGRATION_ERRORS,
  uid,
  clone,
  createIntegrationRecord,
  createWebhookRecord,
  createApiRequest,
  createApiResponse,
  createIntegrationError,
  createIntegrationSuccess,
};
