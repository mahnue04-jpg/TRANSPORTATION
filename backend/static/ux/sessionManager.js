"use strict";
/**
 * sessionManager.js — session persistence for JWT auth.
 *
 * Manages:
 * - Session ID generation and persistence
 * - User identity (name, email, role)
 * - Access/refresh token lifecycle
 * - Session expiry and validation
 *
 * Exported: window.AmiCorSession / module.exports
 */

(function(global) {

const STORAGE_KEY_SESSION  = "amicor_session";
const STORAGE_KEY_IDENTITY = "amicor_identity";
const STORAGE_KEY_RUNTIME_MARKER = "amicor_runtime_marker";
const SESSION_TIMEOUT_MS   = 24 * 60 * 60 * 1000; // 24 hours
const ACCESS_TOKEN_REFRESH_SKEW_MS = 30 * 1000;
const REFRESH_TIMEOUT_MS = 8000;

// ── State ────────────────────────────────────────────────────────────────

let _sessionId    = null;
let _identity     = null;  // { userId, email, name, role, accessToken, refreshToken, tokenExpiresAt, createdAt }
let _isValidated  = false;
let _refreshPromise = null;

// ── Helpers ──────────────────────────────────────────────────────────────

function generateSessionId() {
  return "sess_" + Date.now() + "_" + Math.random().toString(36).substr(2, 9);
}

function currentRuntimeHost() {
  try {
    if (typeof window !== "undefined" && window.location && window.location.host) {
      return normalizeRuntimeHost(String(window.location.host || ""));
    }
  } catch (_) {}
  return "";
}

function normalizeRuntimeHost(host) {
  const value = String(host || "").toLowerCase();
  if (value === "localhost:8010" || value === "127.0.0.1:8010") {
    return "local-dev:8010";
  }
  if (value === "localhost:8011" || value === "127.0.0.1:8011") {
    return "local-dev:8011";
  }
  return value;
}

function emitSessionEvent(name, detail) {
  try {
    if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
    window.dispatchEvent(new CustomEvent(name, {
      detail: Object.assign({
        at: new Date().toISOString(),
        runtimeHost: currentRuntimeHost(),
      }, detail || {}),
    }));
  } catch (_) {}
}

function purgeStorageKeys() {
  try {
    localStorage.removeItem(STORAGE_KEY_SESSION);
    localStorage.removeItem(STORAGE_KEY_IDENTITY);
    localStorage.removeItem(STORAGE_KEY_RUNTIME_MARKER);
  } catch (_) {}
}

function isRuntimeCompatible(identity) {
  const runtimeHost = currentRuntimeHost();
  if (!runtimeHost) return true;

  try {
    const markerRaw = localStorage.getItem(STORAGE_KEY_RUNTIME_MARKER);
    if (markerRaw) {
      const marker = JSON.parse(markerRaw);
      const markerHost = String(marker && marker.runtimeHost ? marker.runtimeHost : "").toLowerCase();
      if (markerHost && markerHost !== runtimeHost) {
        return false;
      }
    }
  } catch (_) {}

  const identityHost = String(identity && identity.runtimeHost ? identity.runtimeHost : "").toLowerCase();
  if (identityHost && identityHost !== runtimeHost) {
    return false;
  }
  return true;
}

function normalizeRole(role) {
  const value = String(role || "staff").trim().toLowerCase();
  if (["admin", "dispatcher", "driver", "provider", "rider", "compliance_officer", "supervisor", "driver_support", "medical_coordinator", "staff"].indexOf(value) === -1) {
    return "staff";
  }
  return value;
}

function hasTokenExpired() {
  if (!_identity || !_identity.tokenExpiresAt) return false;
  return Date.now() >= Number(_identity.tokenExpiresAt || 0);
}

function inferTokenExpiryMs(accessToken) {
  try {
    if (!accessToken) return null;
    const parts = String(accessToken).split(".");
    if (parts.length < 2) return null;
    const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
    const payload = JSON.parse(atob(padded));
    const exp = Number(payload && payload.exp ? payload.exp : 0);
    if (!Number.isFinite(exp) || exp <= 0) return null;
    return exp * 1000;
  } catch (_) {
    return null;
  }
}

function hydrateIdentity(identity) {
  if (!identity) return null;
  const email = String(identity.email || "").trim().toLowerCase();
  const fallbackUserId = (email ? email.split("@")[0] : "user") + "_" + Date.now();
  const runtimeHost = currentRuntimeHost();
  const accessToken = identity.accessToken || identity.access_token || null;
  const explicitExpiry = identity.tokenExpiresAt ? Number(identity.tokenExpiresAt) : null;
  const inferredExpiry = inferTokenExpiryMs(accessToken);
  return {
    userId: String(identity.userId || identity.user_id || fallbackUserId),
    email,
    name: String(identity.name || identity.display_name || email.split("@")[0] || "User"),
    role: normalizeRole(identity.role),
    organizationId: identity.organizationId || identity.organization_id || null,
    organizationName: identity.organization_name ? String(identity.organization_name) : null,
    accessToken,
    refreshToken: identity.refreshToken || identity.refresh_token || null,
    tokenExpiresAt: (Number.isFinite(explicitExpiry) && explicitExpiry > 0) ? explicitExpiry : inferredExpiry,
    createdAt: identity.createdAt || new Date().toISOString(),
    runtimeHost: String(identity.runtimeHost || runtimeHost || "").toLowerCase(),
  };
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
      _identity = ident ? hydrateIdentity(JSON.parse(ident)) : null;
      if (_identity && !isRuntimeCompatible(_identity)) {
        purgeStorageKeys();
        emitSessionEvent("amicor:session-invalid", {
          reason: "runtime_mismatch",
        });
        return null;
      }
      if (_identity && hasTokenExpired() && !_identity.refreshToken) {
        purgeStorageKeys();
        return null;
      }
      _isValidated = true;
      return { sessionId: _sessionId, identity: _identity };
    }
  } catch (_) {}
  return null;
}

function saveToStorage() {
  try {
    const runtimeHost = currentRuntimeHost();
    localStorage.setItem(STORAGE_KEY_SESSION, JSON.stringify({
      id: _sessionId,
      expiresAt: Date.now() + SESSION_TIMEOUT_MS,
      runtimeHost,
    }));
    if (_identity) {
      _identity.runtimeHost = runtimeHost;
      localStorage.setItem(STORAGE_KEY_IDENTITY, JSON.stringify(_identity));
    }
    localStorage.setItem(STORAGE_KEY_RUNTIME_MARKER, JSON.stringify({
      runtimeHost,
      updatedAt: new Date().toISOString(),
    }));
  } catch (_) {}
}

// ── Public API ───────────────────────────────────────────────────────────

const AmiCorSession = {
  /**
   * Start a new session with a given identity.
   * identity: { email, name }
   */
  start(identity) {
    const hadActiveSession = !!(_sessionId && _identity && _identity.accessToken);
    _sessionId = generateSessionId();
    _identity = hydrateIdentity(identity);
    _isValidated = true;
    saveToStorage();
    emitSessionEvent("amicor:session-recovered", {
      reason: hadActiveSession ? "session_replaced" : "session_started",
      userId: _identity && _identity.userId ? _identity.userId : null,
      organizationId: _identity && _identity.organizationId ? _identity.organizationId : null,
    });
    return { sessionId: _sessionId, identity: _identity };
  },

  /**
   * Restore session from storage if valid.
   * Returns { sessionId, identity } or null.
   */
  restore() {
    const result = loadFromStorage();
    return result || this.getCurrent();
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

  getRole() {
    return _identity ? normalizeRole(_identity.role) : null;
  },

  /**
   * Persist a workspace role selection for the active session.
   * This updates client-side session identity only; JWT role claims are unchanged.
   */
  updateWorkspaceRole(role) {
    const normalized = normalizeRole(role);
    if (!_identity) {
      const restored = loadFromStorage();
      if (!restored || !restored.identity) {
        return false;
      }
    }
    if (!_identity) {
      return false;
    }
    _identity.role = normalized;
    saveToStorage();
    emitSessionEvent("amicor:workspace-role-updated", {
      role: normalized,
    });
    return true;
  },

  getOrganizationId() {
    if (_identity && _identity.organizationId) {
      return String(_identity.organizationId);
    }
    try {
      const ident = localStorage.getItem(STORAGE_KEY_IDENTITY);
      if (!ident) return null;
      const parsed = JSON.parse(ident);
      const orgId = parsed && (parsed.organizationId || parsed.organization_id);
      if (!orgId) return null;
      if (!_identity) {
        _identity = hydrateIdentity(parsed);
      }
      return String(orgId);
    } catch (_) {
      return null;
    }
  },

  getSessionProfile() {
    const current = this.getCurrent() || {};
    const identity = current.identity || null;
    const active = this.isActive();
    const tokenExpiresAt = identity && identity.tokenExpiresAt ? Number(identity.tokenExpiresAt) : null;
    return {
      sessionId: current.sessionId || null,
      active,
      userId: this.getUserId(),
      email: identity && identity.email ? String(identity.email) : null,
      displayName: identity && identity.name ? String(identity.name) : null,
      role: this.getRole() || "guest",
      organizationId: this.getOrganizationId(),
      organizationName: identity && identity.organizationName ? String(identity.organizationName) : null,
      accessTokenPresent: !!this.getAccessToken(),
      refreshTokenPresent: !!this.getRefreshToken(),
      tokenExpiresAt,
      tokenExpiresInMinutes: tokenExpiresAt ? Math.max(0, Math.round((tokenExpiresAt - Date.now()) / 60000)) : null,
      runtimeHost: currentRuntimeHost(),
    };
  },

  getAuthHeaders(extraHeaders) {
    const headers = Object.assign({}, extraHeaders || {});
    const token = this.getAccessToken();
    if (token) {
      headers.Authorization = "Bearer " + token;
    }
    return headers;
  },

  getAccessToken() {
    if (_identity && _identity.accessToken) {
      return _identity.accessToken;
    }
    // Fallback: check localStorage
    try {
      const ident = localStorage.getItem(STORAGE_KEY_IDENTITY);
      if (ident) {
        const parsed = JSON.parse(ident);
        const storedToken = parsed && (parsed.accessToken || parsed.access_token);
        if (storedToken) {
          _identity = hydrateIdentity(parsed);
          if (!_sessionId) {
            _sessionId = generateSessionId();
            saveToStorage();
          }
          _isValidated = true;
          return String(storedToken);
        }
      }
    } catch (_) {}
    return null;
  },

  getRefreshToken() {
    if (_identity && _identity.refreshToken) {
      return _identity.refreshToken;
    }
    // Fallback: check localStorage
    try {
      const ident = localStorage.getItem(STORAGE_KEY_IDENTITY);
      if (ident) {
        const parsed = JSON.parse(ident);
        const storedRefresh = parsed && (parsed.refreshToken || parsed.refresh_token);
        if (storedRefresh) {
          _identity = hydrateIdentity(parsed);
          _isValidated = true;
          return String(storedRefresh);
        }
      }
    } catch (_) {}
    return null;
  },

  async refreshAccessToken(force) {
    if (_refreshPromise) return _refreshPromise;
    _refreshPromise = this._refreshAccessTokenInner(!!force);
    try {
      return await _refreshPromise;
    } finally {
      _refreshPromise = null;
    }
  },

  async _refreshAccessTokenInner(force) {
    if (!_identity || !_identity.refreshToken) return false;
    if (!force && _identity.tokenExpiresAt && Date.now() < (Number(_identity.tokenExpiresAt) - ACCESS_TOKEN_REFRESH_SKEW_MS)) {
      return true;
    }

    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), REFRESH_TIMEOUT_MS);
      let res;
      try {
        res = await fetch("/api/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: _identity.refreshToken }),
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timeout);
      }
      if (!res.ok) {
        if (res.status === 429 || res.status >= 500) {
          emitSessionEvent("amicor:session-refresh-throttled", {
            status: res.status,
          });
          return false;
        }
        emitSessionEvent("amicor:session-refresh-rejected", {
          status: res.status,
        });
        return false;
      }
      const payload = await res.json();
      _identity.accessToken = payload.access_token || null;
      if (payload.refresh_token) {
        _identity.refreshToken = payload.refresh_token;
      }
      const expiresIn = Number(payload.expires_in || 3600);
      _identity.tokenExpiresAt = Date.now() + (expiresIn * 1000);
      saveToStorage();
      if (force) {
        emitSessionEvent("amicor:session-recovered", {
          reason: "forced_refresh",
        });
      }
      return !!_identity.accessToken;
    } catch (_) {
      return false;
    }
  },

  async authFetch(url, options = {}) {
    if ((!_identity || !_sessionId) && typeof this.restore === "function") {
      this.restore();
    }

    await this.refreshAccessToken(false);
    const buildHeaders = () => {
      const headers = Object.assign({}, options.headers || {});
      if (_identity && _identity.accessToken) {
        headers.Authorization = "Bearer " + _identity.accessToken;
      }
      return headers;
    };

    let response = await fetch(url, Object.assign({}, options, { headers: buildHeaders() }));
    if (response.status !== 401) {
      return response;
    }

    const hadRefresh = !!(_identity && _identity.refreshToken);
    if (!hadRefresh) {
      emitSessionEvent("amicor:session-invalid", {
        reason: "access_401_no_refresh",
        url: String(url || ""),
      });
      return response;
    }

    const refreshed = await this.refreshAccessToken(true);
    if (!refreshed || !_identity || !_identity.accessToken) {
      emitSessionEvent("amicor:session-invalid", {
        reason: "access_401_refresh_failed",
        url: String(url || ""),
      });
      this.clear("access_401_refresh_failed");
      return response;
    }

    const retryResponse = await fetch(url, Object.assign({}, options, { headers: buildHeaders() }));
    if (retryResponse.status === 401) {
      emitSessionEvent("amicor:session-invalid", {
        reason: "access_401_after_retry",
        url: String(url || ""),
      });
      this.clear("access_401_after_retry");
    }
    return retryResponse;
  },

  async logout() {
    const refresh = _identity ? _identity.refreshToken : null;
    try {
      if (refresh) {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
      }
    } catch (_) {}
    this.clear("logout");
  },

  /**
   * Clear session (logout).
   */
  clear(reason) {
    _sessionId = null;
    _identity = null;
    _isValidated = false;
    purgeStorageKeys();
    emitSessionEvent("amicor:session-invalid", {
      reason: String(reason || "cleared"),
    });
  },

  /**
   * Check if session is active.
   */
  isActive() {
    const token = this.getAccessToken(); // Uses fallback
    return !!(_isValidated && _sessionId && _identity && token);
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
