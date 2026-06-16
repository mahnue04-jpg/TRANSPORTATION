"use strict";
/**
 * reconnectHandler.js — MVP offline/reconnect recovery.
 *
 * Handles:
 * - Offline detection (navigator.onLine)
 * - Graceful degradation when backend unavailable
 * - Automatic reconnect with exponential backoff
 * - UI indicators for offline state
 *
 * Exported: window.AmiCorReconnect / module.exports
 */

(function(global) {

const BASE_DELAY_MS = 2000;
const MAX_DELAY_MS = 30000;
const HEARTBEAT_TIMEOUT_MS = 5000;
const RELOAD_FLAG_KEY = "amicor_reconnect_reload_pending";
const RELOAD_FLAG_TTL_MS = 10 * 60 * 1000;
const RELOAD_AFTER_RECONNECT_DELAY_MS = 1200;

let _isOffline = false;
let _reconnectTimer = null;
let _retryCount = 0;
let _statusCallback = null;
let _isMonitoring = false;
let _reloadScheduled = false;

function emitDiag(type, payload) {
  try {
    if (global.AmiCorDiagnostics && typeof global.AmiCorDiagnostics.emitEvent === "function") {
      global.AmiCorDiagnostics.emitEvent(type, Object.assign({ source: "reconnect-handler" }, payload || {}));
    }
  } catch (_) {}
}

// ── State Check ──────────────────────────────────────────────────────────
function markReloadPending() {
  try {
    if (!global.sessionStorage) return;
    global.sessionStorage.setItem(RELOAD_FLAG_KEY, JSON.stringify({ ts: Date.now() }));
  } catch (_) {}
}

function clearReloadPending() {
  try {
    if (!global.sessionStorage) return;
    global.sessionStorage.removeItem(RELOAD_FLAG_KEY);
  } catch (_) {}
}

function hasFreshReloadPending() {
  try {
    if (!global.sessionStorage) return false;
    const raw = global.sessionStorage.getItem(RELOAD_FLAG_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    const ts = Number(parsed && parsed.ts);
    return Number.isFinite(ts) && (Date.now() - ts) <= RELOAD_FLAG_TTL_MS;
  } catch (_) {
    return false;
  }
}

function scheduleReloadAfterReconnect() {
  if (_reloadScheduled) return;
  if (typeof global.location === "undefined" || !global.location || typeof global.location.reload !== "function") {
    return;
  }
  _reloadScheduled = true;
  markReloadPending();
  setTimeout(() => {
    try {
      global.location.reload();
    } catch (_) {
      _reloadScheduled = false;
    }
  }, RELOAD_AFTER_RECONNECT_DELAY_MS);
}

function getReconnectDelay() {
  // Exponential backoff: 2s, 4s, 8s, 16s, 30s, 30s...
  const delay = Math.min(BASE_DELAY_MS * Math.pow(2, _retryCount), MAX_DELAY_MS);
  return delay + Math.random() * 1000; // Add jitter
}

async function checkBackendHealth() {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), HEARTBEAT_TIMEOUT_MS);
    
    const res = await fetch("/api/health", {
      signal: controller.signal,
      method: "GET",
    });
    clearTimeout(timeout);
    
    return res.ok;
  } catch (_) {
    return false;
  }
}

async function attemptReconnect(force = false) {
  if (!_isOffline && !force) return; // Already reconnected

  emitDiag("RECONNECT_ATTEMPT", {
    retryCount: _retryCount,
    online: navigator.onLine,
  });
  
  const isHealthy = await checkBackendHealth();
  if (isHealthy) {
    // Reconnected!
    _isOffline = false;
    _retryCount = 0;
    if (_statusCallback) {
      _statusCallback({ status: "online", message: "Reconnected" });
    }
    emitDiag("RECONNECT_SUCCESS", {
      retryCount: _retryCount,
    });
    if (hasFreshReloadPending()) {
      clearReloadPending();
      scheduleReloadAfterReconnect();
    }
    return true;
  }
  
  // Still offline, schedule retry
  _retryCount++;
  const nextDelay = getReconnectDelay();
  
  if (_statusCallback) {
    _statusCallback({
      status: "reconnecting",
      message: `Attempting to reconnect... (attempt ${_retryCount})`,
      nextRetryMs: nextDelay,
    });
  }

  emitDiag("RECONNECT_SCHEDULED", {
    retryCount: _retryCount,
    nextDelay,
  });
  
  _reconnectTimer = setTimeout(attemptReconnect, nextDelay);
  return false;
}

// ── Monitoring ───────────────────────────────────────────────────────────

function onOnline() {
  _isOffline = false;
  _retryCount = 0;
  clearTimeout(_reconnectTimer);
  if (_statusCallback) {
    _statusCallback({ status: "online", message: "Connection restored" });
  }
  emitDiag("NETWORK_ONLINE", { retryCount: _retryCount });
  if (hasFreshReloadPending()) {
    _isOffline = true;
    attemptReconnect(true);
  }
}

function onOffline() {
  _isOffline = true;
  _retryCount = 0;
  markReloadPending();
  if (_statusCallback) {
    _statusCallback({ status: "offline", message: "No connection" });
  }
  emitDiag("NETWORK_OFFLINE", { retryCount: _retryCount });
  attemptReconnect();
}

// ── Public API ───────────────────────────────────────────────────────────

const AmiCorReconnect = {
  /**
   * Start monitoring online/offline status.
   * callback: (status) => { status: "online" | "offline" | "reconnecting", message, ... }
   */
  startMonitoring(callback) {
    if (_isMonitoring) return;
    _statusCallback = callback;
    _isMonitoring = true;
    
    // Check initial state
    if (!navigator.onLine) {
      _isOffline = true;
      callback({ status: "offline", message: "No connection" });
      emitDiag("RECONNECT_MONITOR_OFFLINE", { retryCount: _retryCount });
      attemptReconnect();
    } else {
      _isOffline = false;
      callback({ status: "online", message: "Connected" });
      emitDiag("RECONNECT_MONITOR_ONLINE", { retryCount: _retryCount });
    }
    
    // Listen for online/offline events
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
  },

  /**
   * Stop monitoring.
   */
  stopMonitoring() {
    if (!_isMonitoring) return;
    _isMonitoring = false;
    clearTimeout(_reconnectTimer);
    window.removeEventListener("online", onOnline);
    window.removeEventListener("offline", onOffline);
    emitDiag("RECONNECT_MONITOR_STOPPED", { retryCount: _retryCount });
  },

  /**
   * Check current status.
   */
  isOnline() {
    return !_isOffline && navigator.onLine;
  },

  /**
   * Check if backend is reachable (health check).
   */
  async checkHealth() {
    return checkBackendHealth();
  },

  /**
   * Manually trigger reconnect attempt.
   */
  manualReconnect() {
    _retryCount = 0;
    return attemptReconnect();
  },

  /**
   * Get current retry count.
   */
  getRetryCount() {
    return _retryCount;
  },
};

// ── Export ───────────────────────────────────────────────────────────────

if (typeof window !== "undefined") {
  window.AmiCorReconnect = AmiCorReconnect;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = AmiCorReconnect;
}

}(typeof window !== "undefined" ? window : global));
