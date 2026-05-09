"use strict";
/**
 * sessionManager.js — MVP session persistence and restoration.
 *
 * Manages:
 * - Session ID generation and persistence
 * - User identity (name, email)
 * - Conversation state restoration
 * - Session expiry and validation
 *
 * Exported: window.AmiCorSession / module.exports
 */

(function(global) {

const STORAGE_KEY_SESSION  = "amicor_session";
const STORAGE_KEY_IDENTITY = "amicor_identity";
const SESSION_TIMEOUT_MS   = 24 * 60 * 60 * 1000; // 24 hours

// ── State ────────────────────────────────────────────────────────────────

let _sessionId    = null;
let _identity     = null;  // { userId, email, name, createdAt }
let _isValidated  = false;

// ── Helpers ──────────────────────────────────────────────────────────────

function generateSessionId() {
  return "sess_" + Date.now() + "_" + Math.random().toString(36).substr(2, 9);
}

function loadFromStorage() {
  try {
    const sess = localStorage.getItem(STORAGE_KEY_SESSION);
    const ident = localStorage.getItem(STORAGE_KEY_IDENTITY);
    
    if (sess) {
      const parsed = JSON.parse(sess);
      // Check expiry
      if (parsed.expiresAt && Date.now() > parsed.expiresAt) {
        localStorage.removeItem(STORAGE_KEY_SESSION);
        localStorage.removeItem(STORAGE_KEY_IDENTITY);
        return null;
      }
      _sessionId = parsed.id;
      _identity = ident ? JSON.parse(ident) : null;
      _isValidated = true;
      return { sessionId: _sessionId, identity: _identity };
    }
  } catch (_) {}
  return null;
}

function saveToStorage() {
  try {
    localStorage.setItem(STORAGE_KEY_SESSION, JSON.stringify({
      id: _sessionId,
      expiresAt: Date.now() + SESSION_TIMEOUT_MS,
    }));
    if (_identity) {
      localStorage.setItem(STORAGE_KEY_IDENTITY, JSON.stringify(_identity));
    }
  } catch (_) {}
}

// ── Public API ───────────────────────────────────────────────────────────

const AmiCorSession = {
  /**
   * Start a new session with a given identity.
   * identity: { email, name }
   */
  start(identity) {
    _sessionId = generateSessionId();
    _identity = {
      userId: identity.email.split("@")[0] + "_" + Date.now(),
      email: identity.email,
      name: identity.name,
      createdAt: new Date().toISOString(),
    };
    _isValidated = true;
    saveToStorage();
    return { sessionId: _sessionId, identity: _identity };
  },

  /**
   * Restore session from storage if valid.
   * Returns { sessionId, identity } or null.
   */
  restore() {
    return loadFromStorage();
  },

  /**
   * Get current session.
   */
  getCurrent() {
    if (!_isValidated) return null;
    return { sessionId: _sessionId, identity: _identity };
  },

  /**
   * Get user ID (for API calls).
   */
  getUserId() {
    return _identity ? _identity.userId : null;
  },

  /**
   * Clear session (logout).
   */
  clear() {
    _sessionId = null;
    _identity = null;
    _isValidated = false;
    try {
      localStorage.removeItem(STORAGE_KEY_SESSION);
      localStorage.removeItem(STORAGE_KEY_IDENTITY);
    } catch (_) {}
  },

  /**
   * Check if session is active.
   */
  isActive() {
    return _isValidated && _sessionId && _identity;
  },
};

// ── Export ───────────────────────────────────────────────────────────────

if (typeof window !== "undefined") {
  window.AmiCorSession = AmiCorSession;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = AmiCorSession;
}

}(typeof window !== "undefined" ? window : global));
