"use strict";

/**
 * SignupPage — form model for new account creation.
 */

function createSignupPage(options) {
  var config = Object.assign(
    {
      onSignup: null,        // async function(email, password, displayName, deviceLabel)
      onNavigateLogin: null,
    },
    options || {}
  );

  var state = {
    email: "",
    password: "",
    confirmPassword: "",
    displayName: "",
    deviceLabel: typeof navigator !== "undefined" ? (navigator.userAgent || "browser") : "node",
    error: null,
    loading: false,
    fieldErrors: {},
    success: false,
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
    if (state.password !== state.confirmPassword) {
      errors.confirmPassword = "Passwords do not match";
    }
    if (!state.displayName || state.displayName.trim().length === 0) {
      errors.displayName = "Display name is required";
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
      if (typeof config.onSignup === "function") {
        await config.onSignup(state.email.trim(), state.password, state.displayName.trim(), state.deviceLabel);
      }
      state.success = true;
    } catch (err) {
      state.error = (err && err.message) ? err.message : "Signup failed. Please try again.";
    } finally {
      state.loading = false;
      notify();
    }
  }

  function navigateLogin() {
    if (typeof config.onNavigateLogin === "function") config.onNavigateLogin();
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
    navigateLogin: navigateLogin,
    subscribe: subscribe,
    getState: getState,
  };
}

module.exports = { createSignupPage };
