#!/usr/bin/env node

"use strict";

require.extensions[".jsx"] = require.extensions[".js"];

const {
  createAuthManager,
  createSessionManager,
  createTokenService,
  createPermissionManager,
  createUserProfileManager,
  createUserSettings,
  createWorkflowPersistence,
  createAuthMiddleware,
  ROLES,
  AUTH_ERRORS,
} = require("./auth");

const { createSessionProvider } = require("../../frontend/src/auth/SessionProvider");
const { createSessionRecovery } = require("../../frontend/src/auth/SessionRecovery");
const { createLoginPage } = require("../../frontend/src/auth/LoginPage");
const { createSignupPage } = require("../../frontend/src/auth/SignupPage");
const { createUserSettingsPanel } = require("../../frontend/src/auth/UserSettings");
const { createProfilePanel } = require("../../frontend/src/auth/ProfilePanel");

var tests = [];
var passed = 0;
var failed = 0;

function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

function ok(condition, message) {
  if (!condition) {
    failed += 1;
    console.error("  ✗ FAIL: " + message);
    return false;
  }
  passed += 1;
  console.log("  ✓ " + message);
  return true;
}

// ─── Token Service ──────────────────────────────────────────────────────────

test("tokenService: valid access token round-trip", async function () {
  var svc = createTokenService({ secret: "test-secret" });
  var token = svc.issueAccessToken("user-1", ROLES.user, "sess-1");
  ok(typeof token === "string", "token is a string");

  var result = svc.verifyAccessToken(token);
  ok(result.ok === true, "token verifies successfully");
  ok(result.payload.sub === "user-1", "payload.sub matches userId");
  ok(result.payload.role === ROLES.user, "payload.role matches");
  ok(result.payload.sessionId === "sess-1", "payload.sessionId matches");
});

test("tokenService: invalid token rejected", async function () {
  var svc = createTokenService({ secret: "test-secret" });
  var result = svc.verifyAccessToken("tampered.fake.token");
  ok(result.ok === false, "invalid token is rejected");
  ok(result.error === AUTH_ERRORS.tokenInvalid, "error code is tokenInvalid");
});

test("tokenService: expired token rejected", async function () {
  var svc = createTokenService({ secret: "test-secret", accessTtlMs: 1 });
  var token = svc.issueAccessToken("user-1", ROLES.user, "sess-1");
  await new Promise(function (r) { setTimeout(r, 10); });
  var result = svc.verifyAccessToken(token);
  ok(result.ok === false, "expired token is rejected");
  ok(result.error === AUTH_ERRORS.tokenExpired, "error code is tokenExpired");
});

test("tokenService: refresh token issues new access token", async function () {
  var svc = createTokenService({ secret: "test-secret" });
  var refresh = svc.issueRefreshToken("user-2", ROLES.admin, "sess-2");
  var result = svc.refreshAccessToken(refresh, "sess-2");
  ok(result.ok === true, "refresh produces new access token");
  ok(typeof result.accessToken === "string", "new access token is a string");
  ok(result.userId === "user-2", "refreshed userId matches");
});

test("tokenService: wrong type rejected", async function () {
  var svc = createTokenService({ secret: "test-secret" });
  var refresh = svc.issueRefreshToken("user-1", ROLES.user, "sess-1");
  var result = svc.verifyAccessToken(refresh); // passing refresh token where access expected
  ok(result.ok === false, "wrong token type rejected");
});

// ─── Session Manager ─────────────────────────────────────────────────────────

test("sessionManager: create and retrieve session", async function () {
  var mgr = createSessionManager({ sessionTtlMs: 60000 });
  var session = mgr.createSession({ userId: "u1", deviceLabel: "desktop" });
  ok(session.userId === "u1", "session userId is correct");
  ok(session.status === "active", "session is active");

  var retrieved = mgr.getSession(session.id);
  ok(retrieved !== null, "session can be retrieved");
  ok(retrieved.id === session.id, "retrieved session id matches");
});

test("sessionManager: expired session is invalidated", async function () {
  var mgr = createSessionManager({ sessionTtlMs: 1 });
  var session = mgr.createSession({ userId: "u2" });
  await new Promise(function (r) { setTimeout(r, 10); });
  var valid = mgr.isSessionValid(session.id);
  ok(valid === false, "expired session is not valid");

  var retrieved = mgr.getSession(session.id);
  ok(retrieved.status === "expired", "session status becomes expired");
});

test("sessionManager: revoke session", async function () {
  var mgr = createSessionManager();
  var session = mgr.createSession({ userId: "u3" });
  mgr.revokeSession(session.id);
  ok(!mgr.isSessionValid(session.id), "revoked session is invalid");
});

test("sessionManager: multi-device sessions per user", async function () {
  var mgr = createSessionManager({ maxSessionsPerUser: 3 });
  mgr.createSession({ userId: "u4", deviceLabel: "phone" });
  mgr.createSession({ userId: "u4", deviceLabel: "tablet" });
  mgr.createSession({ userId: "u4", deviceLabel: "desktop" });
  var list = mgr.listUserSessions("u4");
  ok(list.length === 3, "three sessions exist for user");

  // Adding a 4th should evict the oldest
  mgr.createSession({ userId: "u4", deviceLabel: "laptop" });
  var newList = mgr.listUserSessions("u4");
  ok(newList.length === 3, "oldest session evicted to enforce max limit");
});

test("sessionManager: revoke all user sessions", async function () {
  var mgr = createSessionManager();
  mgr.createSession({ userId: "u5", deviceLabel: "phone" });
  mgr.createSession({ userId: "u5", deviceLabel: "tablet" });
  var count = mgr.revokeAllUserSessions("u5");
  ok(count === 2, "both sessions revoked");
  ok(mgr.listUserSessions("u5").length === 0, "no active sessions remain");
});

// ─── Auth Manager ────────────────────────────────────────────────────────────

test("authManager: signup and login", async function () {
  var mgr = createAuthManager();
  var signupResult = mgr.signup({ email: "alice@example.com", password: "securePass1" });
  ok(signupResult.ok === true, "signup succeeds");
  ok(typeof signupResult.userId === "string", "userId returned");
  ok(typeof signupResult.accessToken === "string", "accessToken returned");
  ok(typeof signupResult.refreshToken === "string", "refreshToken returned");

  var loginResult = mgr.login({ email: "alice@example.com", password: "securePass1" });
  ok(loginResult.ok === true, "login succeeds with correct password");
  ok(loginResult.userId === signupResult.userId, "login returns same userId");
});

test("authManager: duplicate signup rejected", async function () {
  var mgr = createAuthManager();
  mgr.signup({ email: "bob@example.com", password: "password123" });
  var second = mgr.signup({ email: "bob@example.com", password: "differentpass" });
  ok(second.ok === false, "duplicate signup rejected");
  ok(second.error === AUTH_ERRORS.userAlreadyExists, "correct error code returned");
});

test("authManager: invalid email rejected", async function () {
  var mgr = createAuthManager();
  var result = mgr.signup({ email: "not-an-email", password: "password123" });
  ok(result.ok === false, "invalid email rejected");
  ok(result.error === AUTH_ERRORS.invalidEmail, "correct error code");
});

test("authManager: weak password rejected", async function () {
  var mgr = createAuthManager();
  var result = mgr.signup({ email: "carol@example.com", password: "short" });
  ok(result.ok === false, "weak password rejected");
  ok(result.error === AUTH_ERRORS.weakPassword, "correct error code");
});

test("authManager: wrong password rejected", async function () {
  var mgr = createAuthManager();
  mgr.signup({ email: "dan@example.com", password: "correctPassword" });
  var result = mgr.login({ email: "dan@example.com", password: "wrongPassword" });
  ok(result.ok === false, "wrong password rejected");
  ok(result.error === AUTH_ERRORS.invalidCredentials, "correct error code");
});

test("authManager: concurrent logins from multiple devices", async function () {
  var mgr = createAuthManager();
  mgr.signup({ email: "eve@example.com", password: "multiDevice1" });
  var login1 = mgr.login({ email: "eve@example.com", password: "multiDevice1", deviceLabel: "phone" });
  var login2 = mgr.login({ email: "eve@example.com", password: "multiDevice1", deviceLabel: "desktop" });
  ok(login1.ok && login2.ok, "both logins succeed");
  ok(login1.sessionId !== login2.sessionId, "different sessions created per device");
});

test("authManager: logout invalidates session", async function () {
  var mgr = createAuthManager();
  var s = mgr.signup({ email: "frank@example.com", password: "logoutTest1" });
  var result = mgr.logout(s.sessionId);
  ok(result.ok, "logout succeeds");
  ok(!mgr._sessionManager.isSessionValid(s.sessionId), "session is invalidated");
});

test("authManager: refresh session with valid refresh token", async function () {
  var mgr = createAuthManager();
  var s = mgr.signup({ email: "grace@example.com", password: "refreshTest1" });
  var result = mgr.refreshSession(s.refreshToken);
  ok(result.ok === true, "session refresh succeeds");
  ok(typeof result.accessToken === "string", "new access token issued");
});

test("authManager: refresh with expired refresh token fails", async function () {
  var tokenSvc = createTokenService({ secret: "t", refreshTtlMs: 1 });
  var sessMgr = createSessionManager();
  var mgr = createAuthManager({ tokenService: tokenSvc, sessionManager: sessMgr });
  var s = mgr.signup({ email: "harry@example.com", password: "expiredRefresh1" });
  await new Promise(function (r) { setTimeout(r, 10); });
  var result = mgr.refreshSession(s.refreshToken);
  ok(result.ok === false, "expired refresh token rejected");
});

test("authManager: changePassword works correctly", async function () {
  var mgr = createAuthManager();
  var s = mgr.signup({ email: "ian@example.com", password: "oldPassword1" });
  var change = mgr.changePassword({ userId: s.userId, currentPassword: "oldPassword1", newPassword: "newPassword1" });
  ok(change.ok === true, "password change succeeds");
  var loginOld = mgr.login({ email: "ian@example.com", password: "oldPassword1" });
  var loginNew = mgr.login({ email: "ian@example.com", password: "newPassword1" });
  ok(loginOld.ok === false, "old password rejected after change");
  ok(loginNew.ok === true, "new password accepted");
});

// ─── Permission Manager ───────────────────────────────────────────────────────

test("permissionManager: role hierarchy checks", async function () {
  var pm = createPermissionManager();
  ok(pm.checkRole(ROLES.owner, ROLES.admin), "owner satisfies admin requirement");
  ok(pm.checkRole(ROLES.admin, ROLES.user), "admin satisfies user requirement");
  ok(!pm.checkRole(ROLES.user, ROLES.admin), "user does not satisfy admin requirement");
  ok(!pm.checkRole(ROLES.guest, ROLES.user), "guest does not satisfy user requirement");
});

test("permissionManager: built-in permission checks", async function () {
  var pm = createPermissionManager();
  ok(pm.check("u1", ROLES.user, "write:own"), "user has write:own permission");
  ok(!pm.check("u1", ROLES.user, "manage:users"), "user does not have manage:users");
  ok(pm.check("u1", ROLES.admin, "manage:users"), "admin has manage:users");
  ok(pm.check("u1", ROLES.owner, "any:perm"), "owner has wildcard permission");
});

test("permissionManager: permission escalation attempt blocked", async function () {
  var pm = createPermissionManager();
  // A user-role account cannot escalate to admin permissions
  var result = pm.assertRole(ROLES.user, ROLES.admin);
  ok(result.ok === false, "permission escalation attempt blocked");
  ok(result.error === AUTH_ERRORS.roleTooLow, "correct error code returned");
});

test("permissionManager: grant/revoke extra permissions", async function () {
  var pm = createPermissionManager();
  pm.grantPermission("u2", "custom:export");
  ok(pm.check("u2", ROLES.user, "custom:export"), "extra permission granted");
  pm.revokePermission("u2", "custom:export");
  ok(!pm.check("u2", ROLES.user, "custom:export"), "extra permission revoked");
});

// ─── Cross-user isolation ─────────────────────────────────────────────────────

test("workflowPersistence: cross-user isolation", async function () {
  var persistence = createWorkflowPersistence();
  var wf1 = persistence.saveWorkflow({ userId: "user-A", name: "My Workflow" });
  var wf2 = persistence.saveWorkflow({ userId: "user-B", name: "Their Workflow" });

  var userAWorkflows = persistence.listWorkflows("user-A");
  var userBWorkflows = persistence.listWorkflows("user-B");

  ok(userAWorkflows.length === 1, "user-A has only their own workflow");
  ok(userBWorkflows.length === 1, "user-B has only their own workflow");
  ok(userAWorkflows[0].name === "My Workflow", "user-A sees correct workflow");
  ok(userBWorkflows[0].name === "Their Workflow", "user-B sees correct workflow");

  // user-B cannot retrieve user-A's workflow directly
  var crossAccess = persistence.getWorkflow("user-B", wf1.workflow.id);
  ok(crossAccess.ok === false, "user-B cannot access user-A workflow");
});

test("workflowPersistence: conversation isolation", async function () {
  var persistence = createWorkflowPersistence();
  persistence.saveConversation({ userId: "user-C", title: "C's conversation" });
  persistence.saveConversation({ userId: "user-D", title: "D's conversation" });

  ok(persistence.listConversations("user-C").length === 1, "user-C has 1 conversation");
  ok(persistence.listConversations("user-D").length === 1, "user-D has 1 conversation");
});

// ─── Auth Middleware ─────────────────────────────────────────────────────────

test("authMiddleware: authenticate valid token", async function () {
  var tokenSvc = createTokenService({ secret: "mid-secret" });
  var sessMgr = createSessionManager();
  var mw = createAuthMiddleware({ tokenService: tokenSvc, sessionManager: sessMgr });

  var session = sessMgr.createSession({ userId: "mw-user-1" });
  var token = tokenSvc.issueAccessToken("mw-user-1", ROLES.user, session.id);
  var result = mw.authenticate("Bearer " + token);
  ok(result.ok === true, "valid token authenticated");
  ok(result.context.userId === "mw-user-1", "userId in context");
});

test("authMiddleware: reject missing token", async function () {
  var mw = createAuthMiddleware();
  var result = mw.authenticate(null);
  ok(result.ok === false, "null token rejected");
});

test("authMiddleware: requireOwnership enforces isolation", async function () {
  var mw = createAuthMiddleware();
  var ctx = { userId: "user-X", role: ROLES.user };
  var own = mw.requireOwnership(ctx, "user-X");
  var other = mw.requireOwnership(ctx, "user-Y");
  ok(own.ok === true, "user can access own resource");
  ok(other.ok === false, "user cannot access other user's resource");
});

test("authMiddleware: admin bypasses ownership check", async function () {
  var mw = createAuthMiddleware();
  var ctx = { userId: "admin-1", role: ROLES.admin };
  var result = mw.requireOwnership(ctx, "user-Z");
  ok(result.ok === true, "admin can access any resource");
});

// ─── Session Recovery ─────────────────────────────────────────────────────────

test("sessionRecovery: recovers session with valid refresh token", async function () {
  var storage = { _store: {}, getItem: function (k) { return this._store[k] || null; }, setItem: function (k, v) { this._store[k] = v; }, removeItem: function (k) { delete this._store[k]; } };
  var provider = createSessionProvider({ storage: storage });

  var recovered = false;
  var recovery = createSessionRecovery({
    sessionProvider: provider,
    refreshAdapter: async function (rt) {
      return { ok: true, accessToken: "new-token", refreshToken: rt, userId: "ru-1", email: "r@test.com", role: "user" };
    },
    onRecovered: function () { recovered = true; },
  });

  provider.setSession({ accessToken: null, refreshToken: "valid-refresh", userId: "ru-1", email: "r@test.com", role: "user" });
  // clear access token to simulate expiry scenario
  provider.setSession({ accessToken: null, refreshToken: "valid-refresh", user: { id: "ru-1", role: "user" } });

  await recovery.attemptRecovery();
  var state = recovery.getState();
  ok(state.recovered === true, "session recovery succeeds");
  ok(recovered === true, "onRecovered callback fired");
});

test("sessionRecovery: fails when no refresh token present", async function () {
  var storage = { _store: {}, getItem: function () { return null; }, setItem: function () {}, removeItem: function () {} };
  var provider = createSessionProvider({ storage: storage });
  var failed = false;
  var recovery = createSessionRecovery({
    sessionProvider: provider,
    refreshAdapter: async function () { return { ok: true }; },
    onFailed: function () { failed = true; },
  });

  await recovery.attemptRecovery();
  ok(recovery.getState().failed === true, "recovery fails without refresh token");
  ok(failed === true, "onFailed callback fired");
});

// ─── User Settings ─────────────────────────────────────────────────────────

test("userSettings: get, update, reset", async function () {
  var settings = createUserSettings();
  var getResult = settings.getSettings("u-s1");
  ok(getResult.ok === true, "getSettings returns ok");
  ok(getResult.settings.theme === "system", "default theme is system");

  var updateResult = settings.updateSettings("u-s1", { theme: "dark", language: "es" });
  ok(updateResult.ok === true, "update succeeds");
  ok(updateResult.settings.theme === "dark", "theme updated to dark");
  ok(updateResult.settings.language === "es", "language updated to es");

  var badResult = settings.updateSettings("u-s1", { theme: "rainbow" });
  ok(badResult.ok === false, "invalid theme rejected");

  var resetResult = settings.resetSettings("u-s1");
  ok(resetResult.settings.theme === "system", "settings reset to default");
});

// ─── Profile Manager ─────────────────────────────────────────────────────────

test("userProfileManager: create, update, delete", async function () {
  var pm = createUserProfileManager();
  var create = pm.createProfile({ userId: "p-1", displayName: "Alice" });
  ok(create.ok === true, "profile created");
  ok(create.profile.displayName === "Alice", "displayName set correctly");

  var update = pm.updateProfile("p-1", { displayName: "Alice Smith", bio: "Developer" });
  ok(update.ok === true, "profile updated");
  ok(update.profile.displayName === "Alice Smith", "displayName updated");
  ok(update.profile.bio === "Developer", "bio updated");

  var notFound = pm.getProfile("no-such-user");
  ok(notFound.ok === false, "missing profile returns error");

  pm.deleteProfile("p-1");
  var afterDelete = pm.getProfile("p-1");
  ok(afterDelete.ok === false, "deleted profile not found");
});

// ─── Frontend: LoginPage model ────────────────────────────────────────────────

test("loginPage: validation prevents submit with bad email", async function () {
  var submitCalled = false;
  var page = createLoginPage({ onLogin: async function () { submitCalled = true; } });
  page.setField("email", "not-valid");
  page.setField("password", "somepassword");
  await page.submit();
  ok(!submitCalled, "onLogin not called when email is invalid");
  var state = page.getState();
  ok(state.fieldErrors.email !== undefined, "email field error set");
});

test("loginPage: valid fields call onLogin", async function () {
  var called = false;
  var page = createLoginPage({ onLogin: async function (email, pwd) { called = true; } });
  page.setField("email", "user@example.com");
  page.setField("password", "password123");
  await page.submit();
  ok(called === true, "onLogin called with valid fields");
});

// ─── Frontend: SignupPage model ───────────────────────────────────────────────

test("signupPage: mismatch password blocked", async function () {
  var called = false;
  var page = createSignupPage({ onSignup: async function () { called = true; } });
  page.setField("email", "user@example.com");
  page.setField("password", "password123");
  page.setField("confirmPassword", "different456");
  page.setField("displayName", "Alice");
  await page.submit();
  ok(!called, "onSignup not called with mismatched passwords");
  ok(page.getState().fieldErrors.confirmPassword !== undefined, "confirmPassword error set");
});

test("signupPage: valid fields call onSignup", async function () {
  var called = false;
  var page = createSignupPage({ onSignup: async function () { called = true; } });
  page.setField("email", "new@example.com");
  page.setField("password", "password123");
  page.setField("confirmPassword", "password123");
  page.setField("displayName", "NewUser");
  await page.submit();
  ok(called === true, "onSignup called with valid fields");
});

// ─── Run Tests ────────────────────────────────────────────────────────────────

async function run() {
  console.log("\nAUTH LAYER TESTS");
  console.log("────────────────────────────────────────────────────────────");
  for (var i = 0; i < tests.length; i++) {
    var t = tests[i];
    console.log("\n" + (i + 1) + ". " + t.name);
    try {
      await t.fn();
    } catch (err) {
      failed += 1;
      console.error("  ✗ ERROR: " + (err && err.message ? err.message : String(err)));
    }
  }
  console.log("\n────────────────────────────────────────────────────────────");
  console.log("Results: " + passed + " passed, " + failed + " failed");
  if (failed > 0) {
    process.exit(1);
  }
}

run().catch(function (err) {
  console.error("Fatal:", err);
  process.exit(1);
});
