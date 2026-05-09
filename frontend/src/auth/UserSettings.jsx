"use strict";

/**
 * UserSettings — settings panel view model.
 * Manages local state and delegates to a settings adapter for persistence.
 */

function createUserSettingsPanel(options) {
  var config = Object.assign(
    {
      userId: null,
      settingsAdapter: null, // { getSettings(userId), updateSettings(userId, patch) }
      onSave: null,
    },
    options || {}
  );

  var state = {
    loading: false,
    saving: false,
    error: null,
    successMessage: null,
    settings: null,
    dirty: false,
  };

  var listeners = [];

  function notify() {
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](Object.assign({}, state, { settings: state.settings ? Object.assign({}, state.settings) : null })); } catch (_) {}
    }
  }

  async function load() {
    if (!config.userId || !config.settingsAdapter) return;
    state.loading = true;
    state.error = null;
    notify();
    try {
      var result = await config.settingsAdapter.getSettings(config.userId);
      state.settings = result.ok ? Object.assign({}, result.settings) : null;
      if (!result.ok) state.error = result.message || "Failed to load settings";
    } catch (err) {
      state.error = (err && err.message) || "Failed to load settings";
    } finally {
      state.loading = false;
      notify();
    }
  }

  function setPatch(patch) {
    if (!state.settings) return;
    Object.assign(state.settings, patch);
    state.dirty = true;
    state.successMessage = null;
    notify();
  }

  async function save() {
    if (!config.userId || !config.settingsAdapter || !state.settings) return;
    if (state.saving) return;
    state.saving = true;
    state.error = null;
    state.successMessage = null;
    notify();
    try {
      var result = await config.settingsAdapter.updateSettings(config.userId, state.settings);
      if (result.ok) {
        state.settings = Object.assign({}, result.settings);
        state.dirty = false;
        state.successMessage = "Settings saved successfully";
        if (typeof config.onSave === "function") config.onSave(state.settings);
      } else {
        state.error = result.message || "Failed to save settings";
      }
    } catch (err) {
      state.error = (err && err.message) || "Failed to save settings";
    } finally {
      state.saving = false;
      notify();
    }
  }

  function subscribe(listener) {
    listeners.push(listener);
    return function () {
      listeners = listeners.filter(function (l) { return l !== listener; });
    };
  }

  function getState() {
    return Object.assign({}, state, { settings: state.settings ? Object.assign({}, state.settings) : null });
  }

  return {
    load: load,
    setPatch: setPatch,
    save: save,
    subscribe: subscribe,
    getState: getState,
  };
}

module.exports = { createUserSettingsPanel };
