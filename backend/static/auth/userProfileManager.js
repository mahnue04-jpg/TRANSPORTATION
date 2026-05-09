"use strict";

const { createAuthError, createAuthSuccess, AUTH_ERRORS, clone, uid } = require("./authSchemas");

function createUserProfileManager(options) {
  var config = Object.assign({}, options || {});
  var profiles = new Map(); // userId -> profile

  function createProfile(input) {
    var source = input || {};
    var userId = String(source.userId || "");
    if (!userId) return createAuthError("missing_user_id", "userId is required");

    var profile = {
      userId: userId,
      displayName: String(source.displayName || "").trim() || "User",
      avatar: source.avatar ? String(source.avatar) : null,
      bio: String(source.bio || "").trim(),
      timezone: String(source.timezone || "UTC"),
      locale: String(source.locale || "en"),
      createdAt: Date.now(),
      updatedAt: Date.now(),
      metadata: clone(source.metadata || {}),
    };

    profiles.set(userId, profile);
    return createAuthSuccess({ profile: clone(profile) });
  }

  function getProfile(userId) {
    var profile = profiles.get(String(userId || ""));
    if (!profile) return createAuthError(AUTH_ERRORS.userNotFound, "Profile not found");
    return createAuthSuccess({ profile: clone(profile) });
  }

  function updateProfile(userId, patch) {
    var uid = String(userId || "");
    var profile = profiles.get(uid);
    if (!profile) return createAuthError(AUTH_ERRORS.userNotFound, "Profile not found");

    var p = patch || {};
    if (p.displayName !== undefined) {
      var name = String(p.displayName || "").trim();
      if (name.length === 0) return createAuthError("invalid_display_name", "Display name cannot be empty");
      if (name.length > 64) return createAuthError("invalid_display_name", "Display name too long (max 64 chars)");
      profile.displayName = name;
    }
    if (p.avatar !== undefined) profile.avatar = p.avatar ? String(p.avatar) : null;
    if (p.bio !== undefined) profile.bio = String(p.bio || "").trim().slice(0, 500);
    if (p.timezone !== undefined) profile.timezone = String(p.timezone || "UTC");
    if (p.locale !== undefined) profile.locale = String(p.locale || "en");
    if (p.metadata && typeof p.metadata === "object") {
      Object.assign(profile.metadata, p.metadata);
    }
    profile.updatedAt = Date.now();

    return createAuthSuccess({ profile: clone(profile) });
  }

  function deleteProfile(userId) {
    var existed = profiles.delete(String(userId || ""));
    return createAuthSuccess({ deleted: existed });
  }

  function listProfiles() {
    var result = [];
    profiles.forEach(function (profile) {
      result.push(clone(profile));
    });
    return result;
  }

  function profileCount() {
    return profiles.size;
  }

  return {
    createProfile: createProfile,
    getProfile: getProfile,
    updateProfile: updateProfile,
    deleteProfile: deleteProfile,
    listProfiles: listProfiles,
    profileCount: profileCount,
  };
}

module.exports = { createUserProfileManager };
