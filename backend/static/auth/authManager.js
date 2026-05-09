"use strict";

const crypto = require("crypto");
const {
  ROLES,
  createUser,
  createAuthError,
  createAuthSuccess,
  AUTH_ERRORS,
  isValidEmail,
  isStrongPassword,
  uid,
} = require("./authSchemas");
const { createTokenService } = require("./tokenService");
const { createSessionManager } = require("./sessionManager");

var PBKDF2_ITERATIONS = 100000;
var PBKDF2_KEYLEN = 64;
var PBKDF2_DIGEST = "sha512";

function hashPassword(password, salt) {
  return crypto.pbkdf2Sync(
    String(password),
    String(salt),
    PBKDF2_ITERATIONS,
    PBKDF2_KEYLEN,
    PBKDF2_DIGEST
  ).toString("hex");
}

function generateSalt() {
  return crypto.randomBytes(32).toString("hex");
}

function timingSafeCompare(a, b) {
  var bufA = Buffer.from(String(a), "utf8");
  var bufB = Buffer.from(String(b), "utf8");
  if (bufA.length !== bufB.length) {
    crypto.timingSafeEqual(bufA, Buffer.alloc(bufA.length));
    return false;
  }
  return crypto.timingSafeEqual(bufA, bufB);
}

function createAuthManager(options) {
  var config = Object.assign(
    {
      tokenService: null,
      sessionManager: null,
      secret: undefined,
      maxSessionsPerUser: 5,
    },
    options || {}
  );

  var tokenSvc = config.tokenService || createTokenService({ secret: config.secret });
  var sessionMgr = config.sessionManager || createSessionManager({ maxSessionsPerUser: config.maxSessionsPerUser });

  var users = new Map();
  var emailIndex = new Map();

  var listeners = {};

  function emit(event, data) {
    var handlers = listeners[event];
    if (!handlers) return;
    for (var i = 0; i < handlers.length; i++) {
      try { handlers[i](data); } catch (_) {}
    }
  }

  function on(event, handler) {
    if (!listeners[event]) listeners[event] = [];
    listeners[event].push(handler);
  }

  function signup(input) {
    var opts = input || {};
    var email = String(opts.email || "").toLowerCase().trim();
    var password = String(opts.password || "");
    var role = ROLES[opts.role] || ROLES.user;
    var deviceId = opts.deviceId ? String(opts.deviceId) : uid("device");
    var deviceLabel = opts.deviceLabel ? String(opts.deviceLabel) : "primary";

    if (!isValidEmail(email)) {
      return createAuthError(AUTH_ERRORS.invalidEmail, "Email address is invalid");
    }
    if (!isStrongPassword(password)) {
      return createAuthError(AUTH_ERRORS.weakPassword, "Password must be at least 8 characters");
    }
    if (emailIndex.has(email)) {
      return createAuthError(AUTH_ERRORS.userAlreadyExists, "An account with this email already exists");
    }

    var salt = generateSalt();
    var hash = hashPassword(password, salt);
    var user = createUser({
      email: email,
      passwordHash: hash,
      passwordSalt: salt,
      role: role,
      permissions: [],
    });

    users.set(user.id, user);
    emailIndex.set(email, user.id);

    var session = sessionMgr.createSession({ userId: user.id, deviceId: deviceId, deviceLabel: deviceLabel });
    var accessToken = tokenSvc.issueAccessToken(user.id, user.role, session.id);
    var refreshToken = tokenSvc.issueRefreshToken(user.id, user.role, session.id);

    emit("signup", { userId: user.id, email: email });

    return createAuthSuccess({
      userId: user.id,
      email: user.email,
      role: user.role,
      sessionId: session.id,
      accessToken: accessToken,
      refreshToken: refreshToken,
    });
  }

  function login(input) {
    var opts = input || {};
    var email = String(opts.email || "").toLowerCase().trim();
    var password = String(opts.password || "");
    var deviceId = opts.deviceId ? String(opts.deviceId) : uid("device");
    var deviceLabel = opts.deviceLabel ? String(opts.deviceLabel) : "unknown";

    var userId = emailIndex.get(email);
    if (!userId) {
      // Compute a hash to prevent timing attacks leaking email existence
      hashPassword(password, generateSalt());
      return createAuthError(AUTH_ERRORS.invalidCredentials, "Invalid email or password");
    }

    var user = users.get(userId);
    if (!user || !user.active) {
      hashPassword(password, generateSalt());
      return createAuthError(AUTH_ERRORS.invalidCredentials, "Invalid email or password");
    }

    var computedHash = hashPassword(password, user.passwordSalt);
    if (!timingSafeCompare(computedHash, user.passwordHash)) {
      return createAuthError(AUTH_ERRORS.invalidCredentials, "Invalid email or password");
    }

    var session = sessionMgr.createSession({ userId: user.id, deviceId: deviceId, deviceLabel: deviceLabel });
    var accessToken = tokenSvc.issueAccessToken(user.id, user.role, session.id);
    var refreshToken = tokenSvc.issueRefreshToken(user.id, user.role, session.id);

    emit("login", { userId: user.id, sessionId: session.id });

    return createAuthSuccess({
      userId: user.id,
      email: user.email,
      role: user.role,
      sessionId: session.id,
      accessToken: accessToken,
      refreshToken: refreshToken,
    });
  }

  function logout(sessionId) {
    var result = sessionMgr.revokeSession(sessionId);
    if (result) {
      emit("logout", { sessionId: sessionId });
    }
    return createAuthSuccess({ revoked: !!result });
  }

  function logoutAll(userId) {
    var count = sessionMgr.revokeAllUserSessions(String(userId || ""));
    emit("logoutAll", { userId: userId, sessionCount: count });
    return createAuthSuccess({ revokedCount: count });
  }

  function refreshSession(refreshToken) {
    var verifyResult = tokenSvc.verifyRefreshToken(refreshToken);
    if (!verifyResult.ok) return verifyResult;

    var payload = verifyResult.payload;
    var session = sessionMgr.getSession(payload.sessionId);
    if (!session) {
      return createAuthError(AUTH_ERRORS.sessionExpired, "Session not found");
    }
    if (session.status === "revoked") {
      return createAuthError(AUTH_ERRORS.sessionRevoked, "Session has been revoked");
    }
    if (session.status === "expired" || session.expiresAt < Date.now()) {
      return createAuthError(AUTH_ERRORS.sessionExpired, "Session has expired");
    }

    sessionMgr.touchSession(payload.sessionId);
    var newAccess = tokenSvc.issueAccessToken(payload.sub, payload.role, payload.sessionId);
    var newRefresh = tokenSvc.issueRefreshToken(payload.sub, payload.role, payload.sessionId);

    return createAuthSuccess({
      userId: payload.sub,
      role: payload.role,
      sessionId: payload.sessionId,
      accessToken: newAccess,
      refreshToken: newRefresh,
    });
  }

  function changePassword(input) {
    var opts = input || {};
    var userId = String(opts.userId || "");
    var currentPassword = String(opts.currentPassword || "");
    var newPassword = String(opts.newPassword || "");

    var user = users.get(userId);
    if (!user) {
      return createAuthError(AUTH_ERRORS.userNotFound, "User not found");
    }
    if (!isStrongPassword(newPassword)) {
      return createAuthError(AUTH_ERRORS.weakPassword, "New password must be at least 8 characters");
    }

    var computedHash = hashPassword(currentPassword, user.passwordSalt);
    if (!timingSafeCompare(computedHash, user.passwordHash)) {
      return createAuthError(AUTH_ERRORS.invalidCredentials, "Current password is incorrect");
    }

    var newSalt = generateSalt();
    var newHash = hashPassword(newPassword, newSalt);
    user.passwordHash = newHash;
    user.passwordSalt = newSalt;
    user.updatedAt = Date.now();

    emit("passwordChanged", { userId: userId });
    return createAuthSuccess({ updated: true });
  }

  function getUserById(userId) {
    var user = users.get(String(userId || ""));
    if (!user) return null;
    return { id: user.id, email: user.email, role: user.role, permissions: user.permissions.slice(), createdAt: user.createdAt, active: user.active };
  }

  function getUserByEmail(email) {
    var normalEmail = String(email || "").toLowerCase().trim();
    var userId = emailIndex.get(normalEmail);
    if (!userId) return null;
    return getUserById(userId);
  }

  function deactivateUser(userId) {
    var user = users.get(String(userId || ""));
    if (!user) return createAuthError(AUTH_ERRORS.userNotFound, "User not found");
    user.active = false;
    user.updatedAt = Date.now();
    sessionMgr.revokeAllUserSessions(userId);
    emit("deactivated", { userId: userId });
    return createAuthSuccess({ deactivated: true });
  }

  function userCount() {
    return users.size;
  }

  return {
    signup: signup,
    login: login,
    logout: logout,
    logoutAll: logoutAll,
    refreshSession: refreshSession,
    changePassword: changePassword,
    getUserById: getUserById,
    getUserByEmail: getUserByEmail,
    deactivateUser: deactivateUser,
    userCount: userCount,
    on: on,
    _sessionManager: sessionMgr,
    _tokenService: tokenSvc,
  };
}

module.exports = { createAuthManager };
