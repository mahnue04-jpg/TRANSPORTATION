"use strict";

const { createAuthError, createAuthSuccess, AUTH_ERRORS, clone, uid } = require("./authSchemas");

var DEFAULT_PERSONALITY = "professional";
var VALID_PERSONALITIES = ["professional", "friendly", "concise", "detailed", "creative"];
var VALID_THEMES = ["system", "light", "dark"];
var VALID_LANGUAGES = ["en", "es", "fr", "de", "pt", "it", "ja", "zh"];

function defaultSettings() {
  return {
    theme: "system",
    language: "en",
    assistantPersonality: DEFAULT_PERSONALITY,
    notifications: {
      email: true,
      browser: true,
      workflowComplete: true,
      sessionWarning: true,
    },
    workflow: {
      autoSave: true,
      confirmBeforeDelete: true,
      defaultTimeout: 60000,
    },
    display: {
      compactMode: false,
      showTimestamps: true,
      showToolActivity: true,
    },
  };
}

function createUserSettings(options) {
  var config = Object.assign({}, options || {});
  var store = new Map(); // userId -> settings object

  function ensureSettings(userId) {
    if (!store.has(userId)) {
      store.set(userId, defaultSettings());
    }
    return store.get(userId);
  }

  function getSettings(userId) {
    var uid = String(userId || "");
    var settings = ensureSettings(uid);
    return createAuthSuccess({ settings: clone(settings) });
  }

  function updateSettings(userId, patch) {
    var uid = String(userId || "");
    var settings = ensureSettings(uid);
    var p = patch || {};

    if (p.theme !== undefined) {
      if (VALID_THEMES.indexOf(String(p.theme)) === -1) {
        return createAuthError("invalid_setting", "Theme must be one of: " + VALID_THEMES.join(", "));
      }
      settings.theme = String(p.theme);
    }

    if (p.language !== undefined) {
      if (VALID_LANGUAGES.indexOf(String(p.language)) === -1) {
        return createAuthError("invalid_setting", "Language must be one of: " + VALID_LANGUAGES.join(", "));
      }
      settings.language = String(p.language);
    }

    if (p.assistantPersonality !== undefined) {
      if (VALID_PERSONALITIES.indexOf(String(p.assistantPersonality)) === -1) {
        return createAuthError("invalid_setting", "Personality must be one of: " + VALID_PERSONALITIES.join(", "));
      }
      settings.assistantPersonality = String(p.assistantPersonality);
    }

    if (p.notifications && typeof p.notifications === "object") {
      Object.assign(settings.notifications, p.notifications);
    }

    if (p.workflow && typeof p.workflow === "object") {
      if (typeof p.workflow.defaultTimeout === "number") {
        p.workflow.defaultTimeout = Math.max(5000, Math.min(300000, p.workflow.defaultTimeout));
      }
      Object.assign(settings.workflow, p.workflow);
    }

    if (p.display && typeof p.display === "object") {
      Object.assign(settings.display, p.display);
    }

    return createAuthSuccess({ settings: clone(settings) });
  }

  function resetSettings(userId) {
    var uid = String(userId || "");
    store.set(uid, defaultSettings());
    return createAuthSuccess({ reset: true, settings: clone(store.get(uid)) });
  }

  function deleteSettings(userId) {
    store.delete(String(userId || ""));
    return createAuthSuccess({ deleted: true });
  }

  return {
    getSettings: getSettings,
    updateSettings: updateSettings,
    resetSettings: resetSettings,
    deleteSettings: deleteSettings,
    VALID_THEMES: VALID_THEMES,
    VALID_LANGUAGES: VALID_LANGUAGES,
    VALID_PERSONALITIES: VALID_PERSONALITIES,
  };
}

module.exports = { createUserSettings };
