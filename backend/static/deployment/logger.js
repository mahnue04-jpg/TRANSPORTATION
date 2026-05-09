"use strict";

/**
 * logger.js — Structured, leveled logger with transports and child contexts.
 */

const { LOG_LEVELS, LOG_LEVEL_RANK, createLogEntry } = require("./deploymentSchemas");

const RING_SIZE = 1000;

function createLogger(options) {
  var config = Object.assign(
    {
      level:   LOG_LEVELS.info,    // minimum level to emit
      context: {},                  // default context merged into all entries
      transports: [],               // fn(entry) callbacks
    },
    options || {}
  );

  var ringBuffer = [];
  var transports = config.transports.slice();
  var currentLevel = config.level;

  function shouldLog(level) {
    return (LOG_LEVEL_RANK[level] || 0) >= (LOG_LEVEL_RANK[currentLevel] || 0);
  }

  function write(level, message, extra) {
    if (!shouldLog(level)) return;

    var entry = createLogEntry({
      level,
      message,
      context:   Object.assign({}, config.context, (extra && extra.context) || {}),
      requestId: (extra && extra.requestId) || null,
      traceId:   (extra && extra.traceId) || null,
      spanId:    (extra && extra.spanId) || null,
      error:     (extra && extra.error) ? { message: extra.error.message, stack: extra.error.stack, code: extra.error.code } : null,
    });

    // Ring buffer
    ringBuffer.push(entry);
    if (ringBuffer.length > RING_SIZE) ringBuffer.shift();

    // Emit to transports
    for (var i = 0; i < transports.length; i++) {
      try { transports[i](entry); } catch (_) {}
    }
  }

  function debug(message, extra) { write(LOG_LEVELS.debug, message, extra); }
  function info(message, extra)  { write(LOG_LEVELS.info,  message, extra); }
  function warn(message, extra)  { write(LOG_LEVELS.warn,  message, extra); }
  function error(message, extra) { write(LOG_LEVELS.error, message, extra); }
  function fatal(message, extra) { write(LOG_LEVELS.fatal, message, extra); }

  /**
   * child(context) — returns a sub-logger with merged context.
   */
  function child(context) {
    return createLogger({
      level:      currentLevel,
      context:    Object.assign({}, config.context, context || {}),
      transports: transports.slice(),
    });
  }

  function setLevel(level) {
    if (LOG_LEVELS[level]) currentLevel = LOG_LEVELS[level];
  }

  function addTransport(fn) {
    if (typeof fn === "function") transports.push(fn);
  }

  function getLogs(filter) {
    var entries = ringBuffer.slice();
    if (!filter) return entries;
    if (filter.level) {
      var minRank = LOG_LEVEL_RANK[filter.level] || 0;
      entries = entries.filter(function (e) { return (LOG_LEVEL_RANK[e.level] || 0) >= minRank; });
    }
    if (filter.since) entries = entries.filter(function (e) { return e.timestamp >= filter.since; });
    if (filter.context) {
      var fCtx = filter.context;
      entries = entries.filter(function (e) {
        return Object.keys(fCtx).every(function (k) { return e.context[k] === fCtx[k]; });
      });
    }
    return entries;
  }

  function clearLogs() { ringBuffer = []; }

  return {
    debug,
    info,
    warn,
    error,
    fatal,
    child,
    setLevel,
    addTransport,
    getLogs,
    clearLogs,
    LOG_LEVELS,
  };
}

module.exports = { createLogger };
