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

let _isOffline = false;
let _reconnectTimer = null;
let _retryCount = 0;
let _statusCallback = null;
let _isMonitoring = false;

// ── State Check ──────────────────────────────────────────────────────────

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

async function attemptReconnect() {
  if (!_isOffline) return; // Already reconnected
  
  const isHealthy = await checkBackendHealth();
  if (isHealthy) {
    // Reconnected!
    _isOffline = false;
    _retryCount = 0;
    if (_statusCallback) {
      _statusCallback({ status: "online", message: "Reconnected" });
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
}

function onOffline() {
  _isOffline = true;
  _retryCount = 0;
  if (_statusCallback) {
    _statusCallback({ status: "offline", message: "No connection" });
  }
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
      attemptReconnect();
    } else {
      _isOffline = false;
      callback({ status: "online", message: "Connected" });
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
