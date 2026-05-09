"use strict";

const { createSecurityError } = require("./pathSanitizer");

function normalizePermissions(value) {
  if (!value) {
    return [];
  }
  return Array.isArray(value) ? value.slice() : [String(value)];
}

function ensurePermissions(required, granted, contextName) {
  const requiredList = normalizePermissions(required);
  const grantedList = normalizePermissions(granted);
  const missing = requiredList.filter(function (permission) {
    return grantedList.indexOf(permission) === -1;
  });

  if (missing.length > 0) {
    throw createSecurityError("permission-denied", (contextName || "Tool") + " requires permissions", {
      required: requiredList,
      granted: grantedList,
      missing: missing,
    });
  }

  return true;
}

module.exports = {
  normalizePermissions: normalizePermissions,
  ensurePermissions: ensurePermissions,
};