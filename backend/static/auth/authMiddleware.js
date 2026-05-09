"use strict";

const { ROLES, createAuthError, createAuthSuccess, AUTH_ERRORS } = require("./authSchemas");
const { createTokenService } = require("./tokenService");
const { createSessionManager } = require("./sessionManager");
const { createPermissionManager } = require("./permissionManager");

function createAuthMiddleware(options) {
  var config = Object.assign(
    {
      tokenService: null,
      sessionManager: null,
      permissionManager: null,
      secret: undefined,
    },
    options || {}
  );

  var tokenSvc = config.tokenService || createTokenService({ secret: config.secret });
  var sessionMgr = config.sessionManager || createSessionManager();
  var permMgr = config.permissionManager || createPermissionManager();

  // Attach validated auth context to a plain request object.
  // Returns { ok, context } or an error result.
  function authenticate(bearerToken) {
    if (!bearerToken || typeof bearerToken !== "string") {
      return createAuthError(AUTH_ERRORS.tokenInvalid, "Authorization token is missing");
    }

    var token = bearerToken.replace(/^Bearer\s+/i, "").trim();
    var verifyResult = tokenSvc.verifyAccessToken(token);
    if (!verifyResult.ok) return verifyResult;

    var payload = verifyResult.payload;

    if (payload.sessionId) {
      if (!sessionMgr.isSessionValid(payload.sessionId)) {
        return createAuthError(AUTH_ERRORS.sessionExpired, "Session is no longer valid");
      }
      sessionMgr.touchSession(payload.sessionId);
    }

    return createAuthSuccess({
      context: {
        userId: payload.sub,
        role: payload.role,
        sessionId: payload.sessionId,
        tokenIat: payload.iat,
        tokenExp: payload.exp,
      },
    });
  }

  function requireRole(authContext, requiredRole) {
    if (!authContext) {
      return createAuthError(AUTH_ERRORS.tokenInvalid, "Not authenticated");
    }
    return permMgr.assertRole(authContext.role, requiredRole);
  }

  function requirePermission(authContext, permission) {
    if (!authContext) {
      return createAuthError(AUTH_ERRORS.tokenInvalid, "Not authenticated");
    }
    return permMgr.assertPermission(authContext.userId, authContext.role, permission);
  }

  function requireOwnership(authContext, resourceUserId) {
    if (!authContext) {
      return createAuthError(AUTH_ERRORS.tokenInvalid, "Not authenticated");
    }
    // Admins and owners can access any resource
    var rank = { guest: 0, user: 1, admin: 2, owner: 3 };
    var userRank = rank[authContext.role] || 0;
    if (userRank >= 2) return createAuthSuccess({ allowed: true });

    if (authContext.userId !== String(resourceUserId)) {
      return createAuthError(AUTH_ERRORS.permissionDenied, "Access denied: resource belongs to another user");
    }
    return createAuthSuccess({ allowed: true });
  }

  function isolate(authContext, userId) {
    // Enforce user data isolation: only allow access to own resources unless elevated role
    return requireOwnership(authContext, userId);
  }

  return {
    authenticate: authenticate,
    requireRole: requireRole,
    requirePermission: requirePermission,
    requireOwnership: requireOwnership,
    isolate: isolate,
  };
}

module.exports = { createAuthMiddleware };
