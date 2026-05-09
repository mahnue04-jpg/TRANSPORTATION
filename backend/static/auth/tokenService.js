"use strict";

const crypto = require("crypto");
const { TOKEN_TYPES, createTokenPayload, createAuthError, createAuthSuccess, AUTH_ERRORS } = require("./authSchemas");

var DEFAULT_SECRET = "amicore-default-dev-secret-change-in-production";
var ACCESS_TTL_MS = 60 * 60 * 1000;        // 1 hour
var REFRESH_TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

function base64urlEncode(buf) {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64urlDecode(str) {
  var padded = str.replace(/-/g, "+").replace(/_/g, "/");
  while (padded.length % 4 !== 0) padded += "=";
  return Buffer.from(padded, "base64");
}

function sign(payload, secret) {
  var header = base64urlEncode(Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })));
  var body = base64urlEncode(Buffer.from(JSON.stringify(payload)));
  var sig = base64urlEncode(
    crypto.createHmac("sha256", String(secret || DEFAULT_SECRET)).update(header + "." + body).digest()
  );
  return header + "." + body + "." + sig;
}

function verify(token, secret) {
  if (typeof token !== "string") return null;
  var parts = token.split(".");
  if (parts.length !== 3) return null;
  var expectedSig = base64urlEncode(
    crypto.createHmac("sha256", String(secret || DEFAULT_SECRET)).update(parts[0] + "." + parts[1]).digest()
  );
  if (expectedSig !== parts[2]) return null;
  try {
    return JSON.parse(base64urlDecode(parts[1]).toString("utf8"));
  } catch (_) {
    return null;
  }
}

function createTokenService(options) {
  var config = Object.assign(
    {
      secret: DEFAULT_SECRET,
      accessTtlMs: ACCESS_TTL_MS,
      refreshTtlMs: REFRESH_TTL_MS,
    },
    options || {}
  );

  function issueAccessToken(userId, role, sessionId) {
    var now = Date.now();
    var payload = createTokenPayload({
      sub: userId,
      role: role,
      sessionId: sessionId,
      type: TOKEN_TYPES.access,
      iat: now,
      exp: now + config.accessTtlMs,
    });
    return sign(payload, config.secret);
  }

  function issueRefreshToken(userId, role, sessionId) {
    var now = Date.now();
    var payload = createTokenPayload({
      sub: userId,
      role: role,
      sessionId: sessionId,
      type: TOKEN_TYPES.refresh,
      iat: now,
      exp: now + config.refreshTtlMs,
    });
    return sign(payload, config.secret);
  }

  function issueResetToken(userId) {
    var now = Date.now();
    var payload = createTokenPayload({
      sub: userId,
      role: "user",
      sessionId: "",
      type: TOKEN_TYPES.reset,
      iat: now,
      exp: now + 15 * 60 * 1000, // 15 minutes
    });
    return sign(payload, config.secret);
  }

  function verifyToken(token) {
    var payload = verify(token, config.secret);
    if (!payload) {
      return createAuthError(AUTH_ERRORS.tokenInvalid, "Token signature is invalid");
    }
    if (typeof payload.exp === "number" && payload.exp < Date.now()) {
      return createAuthError(AUTH_ERRORS.tokenExpired, "Token has expired");
    }
    return createAuthSuccess({ payload: payload });
  }

  function verifyAccessToken(token) {
    var result = verifyToken(token);
    if (!result.ok) return result;
    if (result.payload.type !== TOKEN_TYPES.access) {
      return createAuthError(AUTH_ERRORS.tokenInvalid, "Expected access token");
    }
    return result;
  }

  function verifyRefreshToken(token) {
    var result = verifyToken(token);
    if (!result.ok) return result;
    if (result.payload.type !== TOKEN_TYPES.refresh) {
      return createAuthError(AUTH_ERRORS.tokenInvalid, "Expected refresh token");
    }
    return result;
  }

  function refreshAccessToken(refreshToken, sessionId) {
    var result = verifyRefreshToken(refreshToken);
    if (!result.ok) return result;
    var payload = result.payload;
    var newAccess = issueAccessToken(payload.sub, payload.role, sessionId || payload.sessionId);
    return createAuthSuccess({ accessToken: newAccess, userId: payload.sub, role: payload.role });
  }

  function decodeToken(token) {
    if (typeof token !== "string") return null;
    var parts = token.split(".");
    if (parts.length !== 3) return null;
    try {
      return JSON.parse(base64urlDecode(parts[1]).toString("utf8"));
    } catch (_) {
      return null;
    }
  }

  return {
    issueAccessToken: issueAccessToken,
    issueRefreshToken: issueRefreshToken,
    issueResetToken: issueResetToken,
    verifyToken: verifyToken,
    verifyAccessToken: verifyAccessToken,
    verifyRefreshToken: verifyRefreshToken,
    refreshAccessToken: refreshAccessToken,
    decodeToken: decodeToken,
  };
}

module.exports = { createTokenService };
