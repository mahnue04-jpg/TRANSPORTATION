#!/usr/bin/env node

"use strict";

const { createBenchmarkCollector, formatBenchmarkReport } = require("./authBenchmarks");

const {
  createAuthManager,
  createTokenService,
  createSessionManager,
  createPermissionManager,
  createUserProfileManager,
  createUserSettings,
  createWorkflowPersistence,
  ROLES,
} = require("./auth");

var allResults = [];

async function runBatch(label, count, executor) {
  var collector = createBenchmarkCollector();
  var failed = 0;
  console.log("  Running: " + label + " (" + count + " ops)...");
  for (var i = 0; i < count; i++) {
    var start = Date.now();
    try {
      await executor(i);
    } catch (err) {
      failed += 1;
    }
    var elapsed = Date.now() - start;
    collector.recordOp(label, elapsed, { index: i });
  }
  var s = collector.summary();
  allResults.push({ label: label, summary: s, failed: failed });
  console.log(
    "    done: " + s.count + " ops, avg " + s.avgMs.toFixed(2) + "ms, " +
    (failed > 0 ? "✗ " + failed + " failures" : "✓ all passed")
  );
}

async function main() {
  console.log("\nAUTH BENCHMARKS");
  console.log("════════════════════════════════════════════════════════════");

  // ─── 1. Signup throughput ───────────────────────────────────────────────────
  var authMgr = createAuthManager();
  var counter = 0;
  await runBatch("signup-throughput", 100, async function (i) {
    var email = "bench_signup_" + i + "_" + (counter++) + "@test.com";
    var result = authMgr.signup({ email: email, password: "benchPass1234" });
    if (!result.ok) throw new Error(result.message);
  });

  // ─── 2. Login throughput ────────────────────────────────────────────────────
  var loginMgr = createAuthManager();
  for (var i = 0; i < 50; i++) {
    loginMgr.signup({ email: "bench_login_" + i + "@test.com", password: "loginBench1234" });
  }
  await runBatch("login-throughput", 100, async function (i) {
    var email = "bench_login_" + (i % 50) + "@test.com";
    var result = loginMgr.login({ email: email, password: "loginBench1234" });
    if (!result.ok) throw new Error(result.message);
  });

  // ─── 3. Token operations ────────────────────────────────────────────────────
  var tokenSvc = createTokenService({ secret: "bench-secret-token" });
  var accessToken = tokenSvc.issueAccessToken("bench-user", ROLES.user, "sess-bench");
  var refreshToken = tokenSvc.issueRefreshToken("bench-user", ROLES.user, "sess-bench");

  await runBatch("token-issue-access", 200, async function () {
    var t = tokenSvc.issueAccessToken("bench-user", ROLES.user, "sess-bench");
    if (!t) throw new Error("no token");
  });

  await runBatch("token-verify-access", 200, async function () {
    var r = tokenSvc.verifyAccessToken(accessToken);
    if (!r.ok) throw new Error(r.error);
  });

  await runBatch("token-refresh", 100, async function () {
    var r = tokenSvc.refreshAccessToken(refreshToken, "sess-bench");
    if (!r.ok) throw new Error(r.error || "refresh failed");
  });

  // ─── 4. Session management ─────────────────────────────────────────────────
  var sessMgr = createSessionManager({ sessionTtlMs: 60000 * 60 });
  await runBatch("session-create", 200, async function (i) {
    var s = sessMgr.createSession({ userId: "bench-u-" + (i % 10), deviceLabel: "bench-device-" + i });
    if (!s || !s.id) throw new Error("no session");
  });

  await runBatch("session-lookup", 200, async function () {
    var sessions = sessMgr.listUserSessions("bench-u-0");
    if (!sessions) throw new Error("no list");
  });

  await runBatch("session-touch", 100, async function () {
    var sessions = sessMgr.listUserSessions("bench-u-0");
    if (sessions.length > 0) {
      sessMgr.touchSession(sessions[0].id);
    }
  });

  // ─── 5. Permission checks ──────────────────────────────────────────────────
  var pm = createPermissionManager();
  pm.grantPermission("bench-check-user", "custom:export");
  await runBatch("permission-check-role", 500, async function () {
    var r = pm.checkRole(ROLES.admin, ROLES.user);
    if (!r) throw new Error("expected true");
  });

  await runBatch("permission-check-specific", 500, async function () {
    pm.check("bench-check-user", ROLES.user, "write:own");
  });

  // ─── 6. Profile operations ─────────────────────────────────────────────────
  var profileMgr = createUserProfileManager();
  for (var j = 0; j < 20; j++) {
    profileMgr.createProfile({ userId: "bp-" + j, displayName: "Bench User " + j });
  }
  await runBatch("profile-read", 200, async function (i) {
    var r = profileMgr.getProfile("bp-" + (i % 20));
    if (!r.ok) throw new Error("missing profile");
  });

  await runBatch("profile-update", 100, async function (i) {
    var r = profileMgr.updateProfile("bp-" + (i % 20), { bio: "Updated bio " + i });
    if (!r.ok) throw new Error(r.message);
  });

  // ─── 7. User settings ─────────────────────────────────────────────────────
  var userSettingsMgr = createUserSettings();
  await runBatch("settings-get", 200, async function (i) {
    var r = userSettingsMgr.getSettings("bs-" + (i % 20));
    if (!r.ok) throw new Error("settings failed");
  });

  await runBatch("settings-update", 100, async function (i) {
    var themes = ["light", "dark", "system"];
    var r = userSettingsMgr.updateSettings("bs-" + (i % 20), { theme: themes[i % 3] });
    if (!r.ok) throw new Error(r.message);
  });

  // ─── 8. Workflow persistence ──────────────────────────────────────────────
  var persistence = createWorkflowPersistence();
  await runBatch("workflow-save", 200, async function (i) {
    var r = persistence.saveWorkflow({ userId: "bwf-" + (i % 10), name: "Workflow " + i, type: "chat" });
    if (!r.ok) throw new Error("save failed");
  });

  await runBatch("workflow-list", 100, async function (i) {
    persistence.listWorkflows("bwf-" + (i % 10));
  });

  await runBatch("conversation-save", 200, async function (i) {
    var r = persistence.saveConversation({ userId: "bcv-" + (i % 10), title: "Conversation " + i });
    if (!r.ok) throw new Error("save failed");
  });

  console.log(formatBenchmarkReport(allResults));

  var totalFailed = allResults.reduce(function (a, r) { return a + r.failed; }, 0);
  if (totalFailed > 0) {
    console.log("\n✗ " + totalFailed + " total benchmark failures");
    process.exit(1);
  } else {
    console.log("\n✓ All benchmark batches completed successfully");
  }
}

main().catch(function (err) {
  console.error("Fatal:", err);
  process.exit(1);
});
