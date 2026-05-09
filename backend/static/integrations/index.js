"use strict";

/**
 * integrations/index.js — Barrel export for all integration modules.
 */

const { INTEGRATION_STATUS, INTEGRATION_TYPES, CONNECTOR_METHODS, WEBHOOK_EVENTS, INTEGRATION_ERRORS, uid, clone, createIntegrationRecord, createWebhookRecord, createApiRequest, createApiResponse, createIntegrationError, createIntegrationSuccess } = require("./integrationSchemas");
const { createIntegrationManager } = require("./integrationManager");
const { createApiConnector, CIRCUIT_STATES } = require("./apiConnector");
const { createServiceAdapter, createMockProvider } = require("./serviceAdapter");
const { createWebhookSystem } = require("./webhookSystem");
const { createEmailProvider } = require("./emailProvider");
const { createCalendarProvider, RECURRENCE, EVENT_STATUS } = require("./calendarProvider");
const { createDocumentProvider, DOC_TYPES } = require("./documentProvider");
const { createNotificationProvider, NOTIFICATION_TYPES, PRIORITY } = require("./notificationProvider");

module.exports = {
  // Schemas & constants
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

  // Core
  createIntegrationManager,
  createApiConnector,
  CIRCUIT_STATES,
  createServiceAdapter,
  createMockProvider,
  createWebhookSystem,

  // Providers
  createEmailProvider,
  createCalendarProvider,
  RECURRENCE,
  EVENT_STATUS,
  createDocumentProvider,
  DOC_TYPES,
  createNotificationProvider,
  NOTIFICATION_TYPES,
  PRIORITY,
};
