"use strict";

/**
 * frontend/src/integrations/index.js — Barrel export for frontend integration clients.
 */

const { createIntegrationClient } = require("./integrationClient");
const { createWebhookClient } = require("./webhookClient");
const { createNotificationClient } = require("./notificationClient");

module.exports = { createIntegrationClient, createWebhookClient, createNotificationClient };
