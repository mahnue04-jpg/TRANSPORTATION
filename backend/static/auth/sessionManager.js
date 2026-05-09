"use strict";

const { SESSION_STATUS, createSessionRecord, clone } = require("./authSchemas");

var DEFAULT_SESSION_TTL_MS = 24 * 60 * 60 * 1000;  // 24 hours
var DEFAULT_MAX_SESSIONS = 5;

function createSessionManager(options) {
  var config = Object.assign(
    {
      sessionTtlMs: DEFAULT_SESSION_TTL_MS,
      maxSessionsPerUser: DEFAULT_MAX_SESSIONS,
    },
    options || {}
  );

  var sessions = new Map();
  var userSessionIndex = new Map(); // userId -> Set of sessionIds

  function indexSession(session) {
    if (!userSessionIndex.has(session.userId)) {
      userSessionIndex.set(session.userId, new Set());
    }
    userSessionIndex.get(session.userId).add(session.id);
  }

  function evictOldestSession(userId) {
    var sessionIds = userSessionIndex.get(userId);
    if (!sessionIds || sessionIds.size === 0) return;

    var oldest = null;
    sessionIds.forEach(function (sid) {
      var s = sessions.get(sid);
      if (!s) return;
      if (!oldest || s.createdAt < oldest.createdAt) {
        oldest = s;
      }
    });
    if (oldest) {
      oldest.status = SESSION_STATUS.revoked;
      sessionIds.delete(oldest.id);
    }
  }

  function createSession(input) {
    var opts = input || {};
    var userId = String(opts.userId || "");

    // Enforce max sessions per user
    var existingSessions = userSessionIndex.get(userId);
    if (existingSessions && existingSessions.size >= config.maxSessionsPerUser) {
      evictOldestSession(userId);
    }

    var session = createSessionRecord({
      userId: userId,
      deviceId: opts.deviceId,
      deviceLabel: opts.deviceLabel,
      status: SESSION_STATUS.active,
      expiresAt: Date.now() + config.sessionTtlMs,
      metadata: opts.metadata || {},
    });

    sessions.set(session.id, session);
    indexSession(session);
    return clone(session);
  }

  function getSession(sessionId) {
    var session = sessions.get(String(sessionId || ""));
    if (!session) return null;
    return clone(session);
  }

  function touchSession(sessionId) {
    var session = sessions.get(String(sessionId || ""));
    if (!session) return false;
    if (session.status !== SESSION_STATUS.active) return false;
    session.lastSeenAt = Date.now();
    session.expiresAt = Date.now() + config.sessionTtlMs;
    return true;
  }

  function revokeSession(sessionId) {
    var session = sessions.get(String(sessionId || ""));
    if (!session) return false;
    session.status = SESSION_STATUS.revoked;
    var userSessions = userSessionIndex.get(session.userId);
    if (userSessions) {
      userSessions.delete(session.id);
    }
    return true;
  }

  function revokeAllUserSessions(userId) {
    var sessionIds = userSessionIndex.get(String(userId || ""));
    if (!sessionIds || sessionIds.size === 0) return 0;
    var count = 0;
    sessionIds.forEach(function (sid) {
      var s = sessions.get(sid);
      if (s && s.status === SESSION_STATUS.active) {
        s.status = SESSION_STATUS.revoked;
        count += 1;
      }
    });
    sessionIds.clear();
    return count;
  }

  function listUserSessions(userId) {
    var sessionIds = userSessionIndex.get(String(userId || ""));
    if (!sessionIds) return [];
    var results = [];
    sessionIds.forEach(function (sid) {
      var s = sessions.get(sid);
      if (s && s.status === SESSION_STATUS.active) {
        results.push(clone(s));
      }
    });
    return results;
  }

  function isSessionValid(sessionId) {
    var session = sessions.get(String(sessionId || ""));
    if (!session) return false;
    if (session.status !== SESSION_STATUS.active) return false;
    if (session.expiresAt < Date.now()) {
      session.status = SESSION_STATUS.expired;
      var userSessions = userSessionIndex.get(session.userId);
      if (userSessions) userSessions.delete(session.id);
      return false;
    }
    return true;
  }

  function cleanupExpired() {
    var removed = 0;
    sessions.forEach(function (session) {
      if (session.status === SESSION_STATUS.active && session.expiresAt < Date.now()) {
        session.status = SESSION_STATUS.expired;
        var userSessions = userSessionIndex.get(session.userId);
        if (userSessions) userSessions.delete(session.id);
        removed += 1;
      }
    });
    return removed;
  }

  function sessionCount() {
    return sessions.size;
  }

  return {
    createSession: createSession,
    getSession: getSession,
    touchSession: touchSession,
    revokeSession: revokeSession,
    revokeAllUserSessions: revokeAllUserSessions,
    listUserSessions: listUserSessions,
    isSessionValid: isSessionValid,
    cleanupExpired: cleanupExpired,
    sessionCount: sessionCount,
  };
}

module.exports = { createSessionManager };
