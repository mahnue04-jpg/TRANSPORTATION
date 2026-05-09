"use strict";

/**
 * deployment/index.js — Barrel export for all deployment modules.
 */

const { ENVIRONMENTS, LOG_LEVELS, LOG_LEVEL_RANK, HEALTH_STATUSES, METRIC_TYPES, SPAN_STATUS, uid, createLogEntry, createHealthReport, createMetricSample, createRateLimitRecord, createSpan, createErrorRecord } = require("./deploymentSchemas");
const { createEnvironmentConfig } = require("./environmentConfig");
const { createSecretsManager } = require("./secretsManager");
const { createLogger } = require("./logger");
const { createTelemetry } = require("./telemetry");
const { createHealthMonitor } = require("./healthMonitor");
const { createRateLimiter } = require("./rateLimiter");
const { createErrorMonitor } = require("./errorMonitor");
const { createDeploymentValidator } = require("./deploymentValidator");

module.exports = {
  // Schemas & constants
  ENVIRONMENTS,
  LOG_LEVELS,
  LOG_LEVEL_RANK,
  HEALTH_STATUSES,
  METRIC_TYPES,
  SPAN_STATUS,
  uid,
  createLogEntry,
  createHealthReport,
  createMetricSample,
  createRateLimitRecord,
  createSpan,
  createErrorRecord,

  // Modules
  createEnvironmentConfig,
  createSecretsManager,
  createLogger,
  createTelemetry,
  createHealthMonitor,
  createRateLimiter,
  createErrorMonitor,
  createDeploymentValidator,
};
