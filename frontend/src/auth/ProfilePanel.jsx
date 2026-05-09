"use strict";

/**
 * ProfilePanel — user profile view/edit model.
 */

function createProfilePanel(options) {
  var config = Object.assign(
    {
      userId: null,
      profileAdapter: null, // { getProfile(userId), updateProfile(userId, patch) }
      onUpdate: null,
    },
    options || {}
  );

  var state = {
    loading: false,
    saving: false,
    editing: false,
    error: null,
    successMessage: null,
    profile: null,
    draft: null,
  };

  var listeners = [];

  function notify() {
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](getState()); } catch (_) {}
    }
  }

  async function load() {
    if (!config.userId || !config.profileAdapter) return;
    state.loading = true;
    state.error = null;
    notify();
    try {
      var result = await config.profileAdapter.getProfile(config.userId);
      state.profile = result.ok ? Object.assign({}, result.profile) : null;
      if (!result.ok) state.error = result.message || "Failed to load profile";
    } catch (err) {
      state.error = (err && err.message) || "Failed to load profile";
    } finally {
      state.loading = false;
      notify();
    }
  }

  function startEditing() {
    if (!state.profile) return;
    state.editing = true;
    state.draft = Object.assign({}, state.profile);
    state.successMessage = null;
    notify();
  }

  function cancelEditing() {
    state.editing = false;
    state.draft = null;
    state.error = null;
    notify();
  }

  function setDraftField(name, value) {
    if (!state.draft) return;
    state.draft[name] = value;
    state.error = null;
    notify();
  }

  async function save() {
    if (!config.userId || !config.profileAdapter || !state.draft) return;
    if (state.saving) return;

    var displayName = (state.draft.displayName || "").trim();
    if (displayName.length === 0) {
      state.error = "Display name cannot be empty";
      notify();
      return;
    }
    if (displayName.length > 64) {
      state.error = "Display name too long (max 64 characters)";
      notify();
      return;
    }

    state.saving = true;
    state.error = null;
    notify();
    try {
      var result = await config.profileAdapter.updateProfile(config.userId, state.draft);
      if (result.ok) {
        state.profile = Object.assign({}, result.profile);
        state.editing = false;
        state.draft = null;
        state.successMessage = "Profile updated successfully";
        if (typeof config.onUpdate === "function") config.onUpdate(state.profile);
      } else {
        state.error = result.message || "Failed to update profile";
      }
    } catch (err) {
      state.error = (err && err.message) || "Failed to update profile";
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
    return {
      loading: state.loading,
      saving: state.saving,
      editing: state.editing,
      error: state.error,
      successMessage: state.successMessage,
      profile: state.profile ? Object.assign({}, state.profile) : null,
      draft: state.draft ? Object.assign({}, state.draft) : null,
    };
  }

  return {
    load: load,
    startEditing: startEditing,
    cancelEditing: cancelEditing,
    setDraftField: setDraftField,
    save: save,
    subscribe: subscribe,
    getState: getState,
  };
}

module.exports = { createProfilePanel };
