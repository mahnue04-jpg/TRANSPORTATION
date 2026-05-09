"use strict";

/**
 * SessionProvider — manages in-memory session context for the frontend,
 * persisting tokens in a pluggable storage adapter (localStorage-compatible).
 */

var ACCESS_TOKEN_KEY = "amicore:accessToken";
var REFRESH_TOKEN_KEY = "amicore:refreshToken";
var USER_KEY = "amicore:user";

function createSessionProvider(options) {
  var config = Object.assign(
    {
      storage: null,          // { getItem, setItem, removeItem }
      onSessionChange: null,  // function(session | null)
      onSessionExpired: null, // function()
    },
    options || {}
  );

  var storage = config.storage || {
    _store: {},
    getItem: function (k) { return this._store[k] || null; },
    setItem: function (k, v) { this._store[k] = v; },
    removeItem: function (k) { delete this._store[k]; },
  };

  var session = null;
  var listeners = [];

  function notify() {
    if (typeof config.onSessionChange === "function") {
      try { config.onSessionChange(session ? Object.assign({}, session) : null); } catch (_) {}
    }
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](session ? Object.assign({}, session) : null); } catch (_) {}
    }
  }

  function hydrate() {
    try {
      var accessToken = storage.getItem(ACCESS_TOKEN_KEY);
      var refreshToken = storage.getItem(REFRESH_TOKEN_KEY);
      var userJson = storage.getItem(USER_KEY);
      if (accessToken && userJson) {
        var user = JSON.parse(userJson);
        session = { accessToken: accessToken, refreshToken: refreshToken, user: user };
        return true;
      }
    } catch (_) {}
    return false;
  }

  function persist() {
    if (!session) {
      storage.removeItem(ACCESS_TOKEN_KEY);
      storage.removeItem(REFRESH_TOKEN_KEY);
      storage.removeItem(USER_KEY);
    } else {
      storage.setItem(ACCESS_TOKEN_KEY, session.accessToken || "");
      if (session.refreshToken) storage.setItem(REFRESH_TOKEN_KEY, session.refreshToken);
      storage.setItem(USER_KEY, JSON.stringify(session.user || {}));
    }
  }

  function setSession(data) {
    if (!data) {
      session = null;
    } else {
      session = {
        accessToken: String(data.accessToken || ""),
        refreshToken: data.refreshToken ? String(data.refreshToken) : null,
        user: Object.assign({}, data.user || { id: data.userId, email: data.email, role: data.role }),
        sessionId: data.sessionId || null,
      };
    }
    persist();
    notify();
  }

  function clearSession() {
    session = null;
    persist();
    notify();
    if (typeof config.onSessionExpired === "function") {
      try { config.onSessionExpired(); } catch (_) {}
    }
  }

  function getSession() {
    return session ? Object.assign({}, session) : null;
  }

  function getAccessToken() {
    return session ? session.accessToken : null;
  }

  function isAuthenticated() {
    return !!session && !!session.accessToken;
  }

  function getUserRole() {
    return session && session.user ? session.user.role : "guest";
  }

  function updateUser(patch) {
    if (!session) return;
    Object.assign(session.user, patch);
    persist();
    notify();
  }

  function subscribe(listener) {
    listeners.push(listener);
    return function () {
      listeners = listeners.filter(function (l) { return l !== listener; });
    };
  }

  // Attempt to restore from storage on creation
  hydrate();

  return {
    hydrate: hydrate,
    setSession: setSession,
    clearSession: clearSession,
    getSession: getSession,
    getAccessToken: getAccessToken,
    isAuthenticated: isAuthenticated,
    getUserRole: getUserRole,
    updateUser: updateUser,
    subscribe: subscribe,
  };
}

module.exports = { createSessionProvider };
