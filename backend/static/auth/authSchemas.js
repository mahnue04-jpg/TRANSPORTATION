"use strict";

const ROLES = {
  guest: "guest",
  user: "user",
  admin: "admin",
  owner: "owner",
};

const ROLE_RANK = {
  guest: 0,
  user: 1,
  admin: 2,
  owner: 3,
};

const TOKEN_TYPES = {
  access: "access",
  refresh: "refresh",
  reset: "reset",
};

const SESSION_STATUS = {
  active: "active",
  expired: "expired",
  revoked: "revoked",
};

const AUTH_ERRORS = {
  invalidCredentials: "invalid_credentials",
  userNotFound: "user_not_found",
  userAlreadyExists: "user_already_exists",
  tokenExpired: "token_expired",
  tokenInvalid: "token_invalid",
  sessionExpired: "session_expired",
  sessionRevoked: "session_revoked",
  permissionDenied: "permission_denied",
  roleTooLow: "role_too_low",
  weakPassword: "weak_password",
  invalidEmail: "invalid_email",
};

function uid(prefix) {
  return String(prefix || "id") + "-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
}

function clone(value) {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map(clone);
  if (typeof value === "object") {
    var out = {};
    var keys = Object.keys(value);
    for (var i = 0; i < keys.length; i++) {
      out[keys[i]] = clone(value[keys[i]]);
    }
    return out;
  }
  return value;
}

function createUser(input) {
  var source = input || {};
  return {
    id: String(source.id || uid("user")),
    email: String(source.email || "").toLowerCase().trim(),
    passwordHash: String(source.passwordHash || ""),
    passwordSalt: String(source.passwordSalt || ""),
    role: ROLES[source.role] || ROLES.user,
    permissions: Array.isArray(source.permissions) ? source.permissions.slice() : [],
    createdAt: source.createdAt || Date.now(),
    updatedAt: source.updatedAt || Date.now(),
    active: source.active !== false,
  };
}

function createSessionRecord(input) {
  var source = input || {};
  var now = Date.now();
  return {
    id: String(source.id || uid("session")),
    userId: String(source.userId || ""),
    deviceId: String(source.deviceId || uid("device")),
    deviceLabel: String(source.deviceLabel || "unknown"),
    status: SESSION_STATUS[source.status] || SESSION_STATUS.active,
    createdAt: source.createdAt || now,
    lastSeenAt: source.lastSeenAt || now,
    expiresAt: typeof source.expiresAt === "number" ? source.expiresAt : now + 24 * 60 * 60 * 1000,
    metadata: clone(source.metadata || {}),
  };
}

function createTokenPayload(input) {
  var source = input || {};
  return {
    sub: String(source.sub || ""),
    role: String(source.role || ROLES.user),
    sessionId: String(source.sessionId || ""),
    type: TOKEN_TYPES[source.type] || TOKEN_TYPES.access,
    iat: typeof source.iat === "number" ? source.iat : Date.now(),
    exp: typeof source.exp === "number" ? source.exp : Date.now() + 60 * 60 * 1000,
  };
}

function createAuthError(code, message) {
  return { ok: false, error: String(code || "unknown_error"), message: String(message || "") };
}

function createAuthSuccess(data) {
  return Object.assign({ ok: true }, data || {});
}

function isValidEmail(email) {
  return typeof email === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}

function isStrongPassword(password) {
  return typeof password === "string" && password.length >= 8;
}

module.exports = {
  ROLES,
  ROLE_RANK,
  TOKEN_TYPES,
  SESSION_STATUS,
  AUTH_ERRORS,
  uid,
  clone,
  createUser,
  createSessionRecord,
  createTokenPayload,
  createAuthError,
  createAuthSuccess,
  isValidEmail,
  isStrongPassword,
};
