"use strict";

/**
 * SessionRecovery — attempts to recover a valid session from a refresh token,
 * handles token rotation, and emits recovery or failure events.
 */

function createSessionRecovery(options) {
  var config = Object.assign(
    {
      sessionProvider: null,    // SessionProvider instance
      refreshAdapter: null,     // async function(refreshToken) -> AuthResult
      onRecovered: null,        // function(session)
      onFailed: null,           // function(reason)
      autoAttemptOnLoad: true,
    },
    options || {}
  );

  var state = {
    recovering: false,
    recovered: false,
    failed: false,
    failureReason: null,
    attemptedAt: null,
  };

  var listeners = [];

  function notify() {
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](Object.assign({}, state)); } catch (_) {}
    }
  }

  async function attemptRecovery() {
    if (state.recovering) return;
    if (!config.sessionProvider || !config.refreshAdapter) {
      state.failed = true;
      state.failureReason = "No session provider or refresh adapter configured";
      notify();
      return;
    }

    var currentSession = config.sessionProvider.getSession();
    if (!currentSession || !currentSession.refreshToken) {
      state.failed = true;
      state.failureReason = "No refresh token available";
      notify();
      if (typeof config.onFailed === "function") config.onFailed("no_refresh_token");
      return;
    }

    // If already have a valid access token, consider session already valid
    if (currentSession.accessToken && config.sessionProvider.isAuthenticated()) {
      state.recovered = true;
      notify();
      if (typeof config.onRecovered === "function") config.onRecovered(currentSession);
      return;
    }

    state.recovering = true;
    state.failed = false;
    state.failureReason = null;
    state.attemptedAt = Date.now();
    notify();

    try {
      var result = await config.refreshAdapter(currentSession.refreshToken);
      if (result && result.ok) {
        config.sessionProvider.setSession(result);
        state.recovering = false;
        state.recovered = true;
        notify();
        if (typeof config.onRecovered === "function") config.onRecovered(config.sessionProvider.getSession());
      } else {
        var reason = (result && result.message) || "Token refresh failed";
        state.recovering = false;
        state.failed = true;
        state.failureReason = reason;
        config.sessionProvider.clearSession();
        notify();
        if (typeof config.onFailed === "function") config.onFailed(reason);
      }
    } catch (err) {
      var msg = (err && err.message) || "Unexpected error during recovery";
      state.recovering = false;
      state.failed = true;
      state.failureReason = msg;
      config.sessionProvider.clearSession();
      notify();
      if (typeof config.onFailed === "function") config.onFailed(msg);
    }
  }

  function reset() {
    state.recovering = false;
    state.recovered = false;
    state.failed = false;
    state.failureReason = null;
    state.attemptedAt = null;
    notify();
  }

  function subscribe(listener) {
    listeners.push(listener);
    return function () {
      listeners = listeners.filter(function (l) { return l !== listener; });
    };
  }

  function getState() {
    return Object.assign({}, state);
  }

  return {
    attemptRecovery: attemptRecovery,
    reset: reset,
    subscribe: subscribe,
    getState: getState,
  };
}

module.exports = { createSessionRecovery };
