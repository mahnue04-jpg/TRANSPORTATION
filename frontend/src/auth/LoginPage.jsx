"use strict";

/**
 * LoginPage — form model for email/password login with validation state.
 * Designed for CommonJS/JSX compatibility. Renders as a view model
 * consumable by a React component or plain DOM renderer.
 */

function createLoginPage(options) {
  var config = Object.assign(
    {
      onLogin: null,         // async function(email, password, deviceLabel)
      onNavigateSignup: null,
      onNavigateReset: null,
    },
    options || {}
  );

  var state = {
    email: "",
    password: "",
    deviceLabel: typeof navigator !== "undefined" ? (navigator.userAgent || "browser") : "node",
    error: null,
    loading: false,
    fieldErrors: {},
  };

  var listeners = [];

  function notify() {
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](Object.assign({}, state)); } catch (_) {}
    }
  }

  function setField(name, value) {
    state[name] = value;
    state.error = null;
    state.fieldErrors = Object.assign({}, state.fieldErrors);
    delete state.fieldErrors[name];
    notify();
  }

  function validate() {
    var errors = {};
    var emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRe.test((state.email || "").trim())) {
      errors.email = "Enter a valid email address";
    }
    if (!state.password || state.password.length < 8) {
      errors.password = "Password must be at least 8 characters";
    }
    return errors;
  }

  async function submit() {
    if (state.loading) return;
    var errors = validate();
    if (Object.keys(errors).length > 0) {
      state.fieldErrors = errors;
      state.error = "Please fix the errors above";
      notify();
      return;
    }
    state.loading = true;
    state.error = null;
    state.fieldErrors = {};
    notify();

    try {
      if (typeof config.onLogin === "function") {
        await config.onLogin(state.email.trim(), state.password, state.deviceLabel);
      }
    } catch (err) {
      state.error = (err && err.message) ? err.message : "Login failed. Please try again.";
    } finally {
      state.loading = false;
      notify();
    }
  }

  function navigateSignup() {
    if (typeof config.onNavigateSignup === "function") config.onNavigateSignup();
  }

  function navigateReset() {
    if (typeof config.onNavigateReset === "function") config.onNavigateReset();
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
    setField: setField,
    submit: submit,
    navigateSignup: navigateSignup,
    navigateReset: navigateReset,
    subscribe: subscribe,
    getState: getState,
  };
}

module.exports = { createLoginPage };
