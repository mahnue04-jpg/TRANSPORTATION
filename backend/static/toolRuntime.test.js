/**
 * toolRuntime.test.js — AmiCorToolRuntime Test Suite
 *
 * Run from browser console (after loading tools.js):
 *   toolRuntimeTests()
 *   toolRuntimeTests("schema")   ← filter groups by name
 *
 * Requires: tools.js
 */

(function (global) {
  "use strict";

  // ─────────────────────────────────────────────────────────────────────────
  // Test helpers
  // ─────────────────────────────────────────────────────────────────────────

  function ok(cond, desc)   { return { ok: !!cond, desc: desc }; }
  function eq(a, b, desc)   {
    return { ok: a === b, desc: desc,
      detail: a !== b ? ("expected " + JSON.stringify(b) + " got " + JSON.stringify(a)) : undefined };
  }
  function gt(a, b, desc)   {
    return { ok: a > b, desc: desc,
      detail: !(a > b) ? (a + " is not > " + b) : undefined };
  }
  function contains(str, sub, desc) {
    return { ok: typeof str === "string" && str.indexOf(sub) !== -1, desc: desc,
      detail: !(typeof str === "string" && str.indexOf(sub) !== -1)
        ? ('"' + sub + '" not in: ' + String(str).slice(0, 100)) : undefined };
  }
  function lacks(str, sub, desc) {
    return { ok: typeof str !== "string" || str.indexOf(sub) === -1, desc: desc,
      detail: (typeof str === "string" && str.indexOf(sub) !== -1)
        ? ('"' + sub + '" found in: ' + String(str).slice(0, 100)) : undefined };
  }

  /** Collect events from a ToolRuntime instance into an array. */
  function captureRuntimeEvents(rt) {
    var log = [];
    [
      "onToolRegister","onToolUnregister","onExecStart","onExecChunk",
      "onExecComplete","onExecCancel","onExecTimeout","onExecError",
      "onExecRetry","onPermissionDenied",
    ].forEach(function (e) {
      rt.on(e, function (p) { log.push({ event: e, payload: p }); });
    });
    return log;
  }

  /** Wait for N milliseconds (returns Promise). */
  function delay(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  /** Fresh isolated runtime for each group. */
  function rt(opts) {
    return global.AmiCorToolRuntime.createRuntime(opts);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Test groups
  // ─────────────────────────────────────────────────────────────────────────

  var SYNC_GROUPS = [];   // return result directly (or array)
  var ASYNC_GROUPS = [];  // return Promise<result[]>

  function sync(name, fn)  { SYNC_GROUPS.push({ name: name, run: fn }); }
  function async_(name, fn) { ASYNC_GROUPS.push({ name: name, run: fn }); }

  // ══════════════════════════════════════════════════════════════════════════
  // SYNC TESTS
  // ══════════════════════════════════════════════════════════════════════════

  // ── Registry ──────────────────────────────────────────────────────────────
  sync("registry-register-basic", function () {
    var r = rt();
    r.register({ name: "ping", execute: function () { return "pong"; } });
    return [
      ok(r.hasTool("ping"), "hasTool returns true after register"),
      eq(r.listTools()[0].name, "ping", "listTools shows registered tool"),
    ];
  });

  sync("registry-register-no-execute-throws", function () {
    var r = rt(), threw = false;
    try { r.register({ name: "bad" }); } catch (e) { threw = true; }
    return ok(threw, "register without execute() throws");
  });

  sync("registry-register-no-name-throws", function () {
    var r = rt(), threw = false;
    try { r.register({ execute: function () {} }); } catch (e) { threw = true; }
    return ok(threw, "register without name throws");
  });

  sync("registry-unregister", function () {
    var r = rt();
    r.register({ name: "tmp", execute: function () {} });
    r.unregister("tmp");
    return ok(!r.hasTool("tmp"), "hasTool false after unregister");
  });

  sync("registry-unregister-fires-event", function () {
    var r = rt(), log = captureRuntimeEvents(r);
    r.register({ name: "evt-tool", execute: function () {} });
    r.unregister("evt-tool");
    var unregEvt = log.filter(function (e) { return e.event === "onToolUnregister"; });
    return [
      ok(unregEvt.length > 0, "onToolUnregister event fired"),
      eq(unregEvt[0].payload.toolName, "evt-tool", "payload.toolName correct"),
    ];
  });

  sync("registry-register-fires-event", function () {
    var r = rt(), log = captureRuntimeEvents(r);
    r.register({ name: "reg-evt", execute: function () {} });
    var regEvt = log.filter(function (e) { return e.event === "onToolRegister"; });
    return ok(regEvt.length > 0, "onToolRegister event fired");
  });

  // ── Schema validation ──────────────────────────────────────────────────────
  sync("schema-required-field-missing", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      {},
      { query: { type: "string", required: true } }
    );
    return [
      ok(!v.valid, "invalid when required field missing"),
      eq(v.errors[0].code, "required", "error code = required"),
    ];
  });

  sync("schema-type-mismatch", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      { count: "not-a-number" },
      { count: { type: "number", required: true } }
    );
    return [
      ok(!v.valid, "invalid on type mismatch"),
      eq(v.errors[0].code, "type", "error code = type"),
    ];
  });

  sync("schema-enum-violation", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      { mode: "invalid" },
      { mode: { type: "string", enum: ["fast", "slow"] } }
    );
    return ok(!v.valid, "invalid when enum value not allowed");
  });

  sync("schema-minLength", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      { q: "ab" },
      { q: { type: "string", required: true, minLength: 5 } }
    );
    return ok(!v.valid, "invalid when string too short");
  });

  sync("schema-maxLength", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      { q: "toolongstring" },
      { q: { type: "string", required: true, maxLength: 5 } }
    );
    return ok(!v.valid, "invalid when string too long");
  });

  sync("schema-number-min", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      { n: -1 },
      { n: { type: "number", required: true, min: 0 } }
    );
    return ok(!v.valid, "invalid when number below min");
  });

  sync("schema-number-max", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      { n: 999 },
      { n: { type: "number", required: true, max: 100 } }
    );
    return ok(!v.valid, "invalid when number above max");
  });

  sync("schema-valid-passes", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      { query: "hello", limit: 10 },
      {
        query: { type: "string", required: true, minLength: 1 },
        limit: { type: "number", required: true, min: 1, max: 100 },
      }
    );
    return ok(v.valid, "valid schema passes without errors");
  });

  sync("schema-optional-field-absent-ok", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      { name: "alice" },
      {
        name:  { type: "string", required: true },
        extra: { type: "string", required: false },
      }
    );
    return ok(v.valid, "optional absent field does not fail validation");
  });

  sync("schema-strict-unknown-param", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      { known: "yes", unknown: "bad" },
      { known: { type: "string" }, __strict: true }
    );
    return ok(!v.valid, "strict mode rejects unknown params");
  });

  sync("schema-array-type", function () {
    var v = global.AmiCorToolRuntime._validateSchema(
      { items: [1, 2, 3] },
      { items: { type: "array", required: true } }
    );
    return ok(v.valid, "array type accepted correctly");
  });

  // ── Permission model ───────────────────────────────────────────────────────
  sync("permissions-missing-fires-event", function () {
    var r = rt(), denied = null;
    r.on("onPermissionDenied", function (p) { denied = p; });
    r.register({
      name: "secure-tool",
      permissions: ["admin"],
      execute: function () { return "secret"; },
    });
    r.execute("secure-tool", {}, { permissions: [] });
    return [
      ok(denied !== null, "onPermissionDenied fired"),
      contains(denied.required[0], "admin", "denied.required includes 'admin'"),
    ];
  });

  sync("permissions-granted-allows-execution", function () {
    var r = rt();
    var ran = false;
    r.register({
      name: "gated",
      permissions: ["read"],
      execute: function () { ran = true; return "ok"; },
    });
    r.execute("gated", {}, { permissions: ["read"], timeoutMs: 5000 });
    return ok(ran, "tool executes when permission granted");
  });

  sync("permissions-session-inherits", function () {
    var r    = rt();
    var ran  = false;
    r.register({
      name: "session-tool",
      permissions: ["compute"],
      execute: function () { ran = true; return 42; },
    });
    var sess = r.createSession({ permissions: ["compute"] });
    sess.execute("session-tool", {});
    return ok(ran, "session inherits permissions for tool execution");
  });

  // ── Destroy ────────────────────────────────────────────────────────────────
  sync("destroy-throws-on-execute", function () {
    var r = rt(), threw = false;
    r.register({ name: "t", execute: function () { return 1; } });
    r.destroy();
    try { r.execute("t", {}); } catch (e) { threw = true; }
    return ok(threw, "execute() throws after destroy()");
  });

  sync("destroy-throws-on-register", function () {
    var r = rt(), threw = false;
    r.destroy();
    try { r.register({ name: "x", execute: function () {} }); } catch (e) { threw = true; }
    return ok(threw, "register() throws after destroy()");
  });

  sync("session-execute-rejects-after-destroy", function () {
    var r    = rt();
    var sess = r.createSession({ permissions: [] });
    r.register({ name: "t2", execute: function () { return 1; } });
    sess.destroy();
    var rejected = false;
    sess.execute("t2", {}).catch(function () { rejected = true; });
    return ok(rejected, "session.execute() rejects after session.destroy()");
  });

  // ── Metrics ────────────────────────────────────────────────────────────────
  sync("metrics-null-before-first-call", function () {
    var r = rt();
    r.register({ name: "m-tool", execute: function () { return 1; } });
    return ok(r.getMetrics("m-tool") === null, "getMetrics null before first call");
  });

  // ── ToolResult structure ───────────────────────────────────────────────────
  sync("toolresult-frozen", function () {
    var R = global.AmiCorToolRuntime._ToolResult;
    var res = new R({ execId: "e1", toolName: "t", status: "completed",
                      output: "hi", startedAt: Date.now() });
    var threw = false;
    try { res.status = "mutated"; } catch (e) { threw = true; }
    return ok(threw || res.status !== "mutated", "ToolResult is frozen");
  });

  // ══════════════════════════════════════════════════════════════════════════
  // ASYNC TESTS (return Promises)
  // ══════════════════════════════════════════════════════════════════════════

  // ── Basic execution ────────────────────────────────────────────────────────
  async_("exec-sync-tool-success", function () {
    var r = rt();
    r.register({ name: "add", execute: function (args) {
      return { sum: args.a + args.b };
    }});
    return r.execute("add", { a: 3, b: 4 }).then(function (res) { return [
      eq(res.status, "completed", "status = completed"),
      eq(res.output.sum, 7, "output.sum = 7"),
      ok(res.durationMs >= 0, "durationMs >= 0"),
    ]; });
  });

  async_("exec-async-tool-success", function () {
    var r = rt();
    r.register({ name: "async-tool", execute: function (args) {
      return new Promise(function (resolve) {
        setTimeout(function () { resolve({ value: args.x * 2 }); }, 10);
      });
    }});
    return r.execute("async-tool", { x: 5 }, { timeoutMs: 2000 }).then(function (res) { return [
      eq(res.status, "completed", "async tool status = completed"),
      eq(res.output.value, 10, "output.value = 10"),
    ]; });
  });

  async_("exec-tool-not-found", function () {
    var r = rt();
    return r.execute("ghost-tool", {}).then(function (res) { return [
      eq(res.status, "error", "status = error for missing tool"),
      contains(res.error.message, "not found", "error mentions 'not found'"),
    ]; });
  });

  async_("exec-schema-validation-fail", function () {
    var r = rt();
    r.register({
      name: "needs-query",
      schema: { query: { type: "string", required: true, minLength: 3 } },
      execute: function (args) { return args.query.toUpperCase(); },
    });
    return r.execute("needs-query", { query: "ab" }).then(function (res) { return [
      eq(res.status, "error", "status = error on schema failure"),
      contains(res.error.message, "Schema validation", "error describes schema failure"),
    ]; });
  });

  async_("exec-sync-throw-captured", function () {
    var r = rt();
    r.register({ name: "boom", execute: function () {
      throw new Error("kaboom");
    }});
    return r.execute("boom", {}).then(function (res) { return [
      eq(res.status, "error", "status = error on sync throw"),
      contains(res.error.message, "kaboom", "original error message preserved"),
    ]; });
  });

  async_("exec-async-reject-captured", function () {
    var r = rt();
    r.register({ name: "bad-async", execute: function () {
      return Promise.reject(new Error("async-fail"));
    }});
    return r.execute("bad-async", {}, { timeoutMs: 2000 }).then(function (res) { return [
      eq(res.status, "error", "status = error on async rejection"),
      contains(res.error.message, "async-fail", "async error message preserved"),
    ]; });
  });

  // ── Timeout ────────────────────────────────────────────────────────────────
  async_("exec-timeout", function () {
    var r = rt();
    r.register({ name: "slow", execute: function () {
      return new Promise(function (resolve) { setTimeout(resolve, 5000); });
    }});
    return r.execute("slow", {}, { timeoutMs: 50 }).then(function (res) { return [
      eq(res.status, "timeout", "status = timeout"),
      contains(res.error.message, "timed out", "error mentions timed out"),
    ]; });
  });

  async_("exec-timeout-fires-event", function () {
    var r = rt(), log = captureRuntimeEvents(r);
    r.register({ name: "very-slow", execute: function () {
      return new Promise(function (resolve) { setTimeout(resolve, 5000); });
    }});
    return r.execute("very-slow", {}, { timeoutMs: 40 }).then(function () {
      var timeoutEvts = log.filter(function (e) { return e.event === "onExecTimeout"; });
      return ok(timeoutEvts.length > 0, "onExecTimeout event fired");
    });
  });

  async_("exec-timeout-zero-means-immediate", function () {
    var r = rt();
    r.register({ name: "instant-timeout", execute: function () {
      return new Promise(function (resolve) { setTimeout(resolve, 5000); });
    }});
    return r.execute("instant-timeout", {}, { timeoutMs: 1 }).then(function (res) {
      return eq(res.status, "timeout", "timeoutMs=1 causes timeout result");
    });
  });

  // ── Cancellation ───────────────────────────────────────────────────────────
  async_("exec-cancel-active", function () {
    var r = rt(), log = captureRuntimeEvents(r);
    var execId = "cancel-test-" + Date.now();
    r.register({ name: "cancellable", execute: function () {
      return new Promise(function (resolve) { setTimeout(resolve, 5000); });
    }});
    var p = r.execute("cancellable", {}, { execId: execId, timeoutMs: 0 });
    // cancel immediately
    var cancelled = r.cancel(execId);
    return delay(20).then(function () { return [
      ok(cancelled, "cancel() returns true for active exec"),
      ok(
        log.filter(function (e) { return e.event === "onExecCancel"; }).length > 0,
        "onExecCancel event fired"
      ),
      eq(r.activeExecutions().length, 0, "no active executions after cancel"),
    ]; });
  });

  async_("exec-cancel-nonexistent-returns-false", function () {
    var r = rt();
    return delay(0).then(function () {
      return ok(!r.cancel("no-such-exec"), "cancel() returns false for unknown execId");
    });
  });

  async_("exec-cancel-all", function () {
    var r = rt();
    r.register({ name: "multi-slow", execute: function () {
      return new Promise(function (resolve) { setTimeout(resolve, 5000); });
    }});
    r.execute("multi-slow", {}, { timeoutMs: 0 });
    r.execute("multi-slow", {}, { timeoutMs: 0 });
    r.cancelAll();
    return delay(10).then(function () {
      return eq(r.activeExecutions().length, 0, "cancelAll() clears all active executions");
    });
  });

  // ── Retry ──────────────────────────────────────────────────────────────────
  async_("retry-on-failure", function () {
    var r = rt(), attempts = 0;
    r.register({ name: "flaky", execute: function () {
      attempts++;
      if (attempts < 3) return Promise.reject(new Error("transient"));
      return { done: true };
    }});
    return r.execute("flaky", {}, { retryMax: 2, timeoutMs: 5000 }).then(function (res) { return [
      eq(res.status, "completed", "status = completed after retries"),
      eq(res.retryCount, 2, "retryCount = 2"),
      eq(attempts, 3, "tool called 3 times total"),
    ]; });
  });

  async_("retry-fires-event", function () {
    var r = rt(), log = captureRuntimeEvents(r);
    r.register({ name: "fail-once", execute: function () {
      if (!this._called) { this._called = true; return Promise.reject(new Error("first")); }
      return "ok";
    }});
    // Use closure instead of 'this'
    var callCount = 0;
    r.unregister("fail-once");
    r.register({ name: "fail-once", execute: function () {
      callCount++;
      if (callCount === 1) return Promise.reject(new Error("first"));
      return "ok";
    }});
    return r.execute("fail-once", {}, { retryMax: 1, timeoutMs: 5000 }).then(function (res) {
      var retryEvts = log.filter(function (e) { return e.event === "onExecRetry"; });
      return [
        ok(retryEvts.length > 0, "onExecRetry fired"),
        eq(res.status, "completed", "final status = completed"),
      ];
    });
  });

  async_("retry-max-exceeded-returns-error", function () {
    var r = rt();
    r.register({ name: "always-fail", execute: function () {
      return Promise.reject(new Error("permanent"));
    }});
    return r.execute("always-fail", {}, { retryMax: 2, timeoutMs: 5000 }).then(function (res) { return [
      eq(res.status, "error", "status = error after max retries"),
      eq(res.retryCount, 2, "retryCount = 2 in final result"),
    ]; });
  });

  // ── Streaming chunks ───────────────────────────────────────────────────────
  async_("streaming-chunks-via-onChunk-option", function () {
    var r = rt(), chunks = [];
    r.register({ name: "streamer", execute: function (args, ctx) {
      ctx.emitChunk("part1");
      ctx.emitChunk("part2");
      ctx.emitChunk("part3");
      return { total: 3 };
    }});
    return r.execute("streamer", {}, {
      onChunk: function (c) { chunks.push(c); },
      timeoutMs: 5000,
    }).then(function (res) { return [
      eq(res.status, "completed", "streaming tool completes"),
      eq(res.chunks.length, 3, "result.chunks has 3 entries"),
      eq(chunks[0], "part1", "first chunk = 'part1'"),
      eq(chunks[2], "part3", "third chunk = 'part3'"),
    ]; });
  });

  async_("streaming-chunks-fire-events", function () {
    var r = rt(), log = captureRuntimeEvents(r);
    r.register({ name: "chunk-emitter", execute: function (args, ctx) {
      ctx.emitChunk("a"); ctx.emitChunk("b");
      return "done";
    }});
    return r.execute("chunk-emitter", {}, { timeoutMs: 5000 }).then(function () {
      var chunkEvts = log.filter(function (e) { return e.event === "onExecChunk"; });
      return [
        eq(chunkEvts.length, 2, "onExecChunk fires for each chunk"),
        eq(chunkEvts[0].payload.chunk, "a", "first chunk event payload"),
      ];
    });
  });

  // ── Event ordering ─────────────────────────────────────────────────────────
  async_("event-order-start-then-complete", function () {
    var r = rt(), log = captureRuntimeEvents(r);
    r.register({ name: "evtool", execute: function () { return 1; }});
    return r.execute("evtool", {}, { timeoutMs: 5000 }).then(function () {
      var names = log.map(function (e) { return e.event; });
      return [
        eq(names[0], "onExecStart", "first event = onExecStart"),
        ok(names.indexOf("onExecComplete") !== -1, "onExecComplete fired"),
        ok(names.indexOf("onExecStart") < names.indexOf("onExecComplete"),
           "onExecStart precedes onExecComplete"),
      ];
    });
  });

  async_("event-order-error-after-start", function () {
    var r = rt(), log = captureRuntimeEvents(r);
    r.register({ name: "err-tool", execute: function () {
      throw new Error("immediate");
    }});
    return r.execute("err-tool", {}, { timeoutMs: 5000 }).then(function () {
      var names = log.map(function (e) { return e.event; });
      return [
        ok(names.indexOf("onExecStart") !== -1, "onExecStart fired"),
        ok(names.indexOf("onExecError") !== -1, "onExecError fired"),
        ok(names.indexOf("onExecStart") < names.indexOf("onExecError"),
           "onExecStart before onExecError"),
      ];
    });
  });

  // ── Simultaneous executions ────────────────────────────────────────────────
  async_("simultaneous-three-tools", function () {
    var r = rt();
    r.register({ name: "concurrent", execute: function (args) {
      return new Promise(function (resolve) {
        setTimeout(function () { resolve({ id: args.id }); }, args.delay || 20);
      });
    }});
    return Promise.all([
      r.execute("concurrent", { id: 1, delay: 30 }, { timeoutMs: 2000 }),
      r.execute("concurrent", { id: 2, delay: 10 }, { timeoutMs: 2000 }),
      r.execute("concurrent", { id: 3, delay: 20 }, { timeoutMs: 2000 }),
    ]).then(function (results) { return [
      eq(results.length, 3, "all 3 executions resolved"),
      eq(results[0].output.id, 1, "result[0] id correct"),
      eq(results[1].output.id, 2, "result[1] id correct"),
      eq(results[2].output.id, 3, "result[2] id correct"),
    ]; });
  });

  async_("simultaneous-metrics-active-count", function () {
    var r = rt(), activeSnap = 0;
    r.register({ name: "active-check", execute: function (args) {
      return new Promise(function (resolve) {
        setTimeout(function () { resolve(1); }, 30);
      });
    }});
    r.execute("active-check", {}, { timeoutMs: 2000 });
    r.execute("active-check", {}, { timeoutMs: 2000 });
    // Both are now in-flight; check active list
    activeSnap = r.activeExecutions().length;
    return delay(100).then(function () { return [
      eq(activeSnap, 2, "2 executions active simultaneously"),
      eq(r.activeExecutions().length, 0, "0 active after both finish"),
    ]; });
  });

  // ── Metrics ────────────────────────────────────────────────────────────────
  async_("metrics-success-recorded", function () {
    var r = rt();
    r.register({ name: "metric-ok", execute: function () { return "yes"; }});
    return r.execute("metric-ok", {}, { timeoutMs: 5000 }).then(function () {
      var m = r.getMetrics("metric-ok");
      return [
        eq(m.callCount, 1, "callCount = 1"),
        eq(m.successCount, 1, "successCount = 1"),
        eq(m.errorCount, 0, "errorCount = 0"),
      ];
    });
  });

  async_("metrics-failure-recorded", function () {
    var r = rt();
    r.register({ name: "metric-err", execute: function () {
      throw new Error("fail");
    }});
    return r.execute("metric-err", {}, { timeoutMs: 5000 }).then(function () {
      var m = r.getMetrics("metric-err");
      return [
        eq(m.callCount, 1, "callCount = 1"),
        eq(m.errorCount, 1, "errorCount = 1"),
        ok(m.failureRate > 0, "failureRate > 0"),
      ];
    });
  });

  async_("metrics-timeout-recorded", function () {
    var r = rt();
    r.register({ name: "metric-timeout", execute: function () {
      return new Promise(function (resolve) { setTimeout(resolve, 5000); });
    }});
    return r.execute("metric-timeout", {}, { timeoutMs: 30 }).then(function () {
      var m = r.getMetrics("metric-timeout");
      return eq(m.timeoutCount, 1, "timeoutCount = 1");
    });
  });

  async_("metrics-getAll-returns-array", function () {
    var r = rt();
    r.register({ name: "ma1", execute: function () { return 1; }});
    r.register({ name: "ma2", execute: function () { return 2; }});
    return Promise.all([
      r.execute("ma1", {}, { timeoutMs: 2000 }),
      r.execute("ma2", {}, { timeoutMs: 2000 }),
    ]).then(function () {
      var all = r.getMetrics();
      return ok(Array.isArray(all) && all.length >= 2, "getAll returns array with >= 2 entries");
    });
  });

  // ── Permission + schema combined ───────────────────────────────────────────
  async_("permission-and-schema-both-checked", function () {
    var r = rt();
    r.register({
      name: "double-gate",
      permissions: ["superuser"],
      schema: { value: { type: "number", required: true } },
      execute: function (args) { return args.value * 2; },
    });
    // Wrong permissions, right schema
    return r.execute("double-gate", { value: 5 }, { permissions: [] }).then(function (res) {
      return [
        eq(res.status, "error", "status = error when permission missing"),
        contains(res.error.message, "Permission denied", "error is permission-related"),
      ];
    });
  });

  // ── Isolated execution context ────────────────────────────────────────────
  async_("ctx-hasPermission-true", function () {
    var r = rt(), captured = null;
    r.register({
      name: "ctx-tool",
      permissions: ["read"],
      execute: function (args, ctx) {
        captured = ctx.hasPermission("read");
        return "ok";
      },
    });
    return r.execute("ctx-tool", {}, { permissions: ["read"], timeoutMs: 2000 }).then(function () {
      return ok(captured === true, "ctx.hasPermission('read') = true");
    });
  });

  async_("ctx-hasPermission-false", function () {
    var r = rt(), captured = null;
    r.register({
      name: "ctx-tool2",
      permissions: ["write"],
      execute: function (args, ctx) {
        captured = ctx.hasPermission("admin");
        return "ok";
      },
    });
    return r.execute("ctx-tool2", {}, { permissions: ["write"], timeoutMs: 2000 }).then(function () {
      return ok(captured === false, "ctx.hasPermission('admin') = false for non-granted cap");
    });
  });

  async_("ctx-isCancelled-false-during-normal-run", function () {
    var r = rt(), captured = null;
    r.register({
      name: "cancel-ctx",
      execute: function (args, ctx) {
        captured = ctx.isCancelled();
        return "done";
      },
    });
    return r.execute("cancel-ctx", {}, { timeoutMs: 2000 }).then(function () {
      return ok(captured === false, "ctx.isCancelled() = false during normal execution");
    });
  });

  // ── Partial failure recovery ───────────────────────────────────────────────
  async_("partial-failure-other-tools-unaffected", function () {
    var r = rt();
    r.register({ name: "ok-tool",  execute: function () { return "ok"; }});
    r.register({ name: "bad-tool", execute: function () {
      return Promise.reject(new Error("bad"));
    }});
    return Promise.all([
      r.execute("ok-tool",  {}, { timeoutMs: 2000 }),
      r.execute("bad-tool", {}, { timeoutMs: 2000 }),
    ]).then(function (results) { return [
      eq(results[0].status, "completed", "ok-tool completed"),
      eq(results[1].status, "error",     "bad-tool errored"),
    ]; });
  });

  // ── Malformed inputs ───────────────────────────────────────────────────────
  async_("malformed-null-args-handled", function () {
    var r = rt();
    r.register({ name: "null-args", execute: function (args) {
      return { received: args };
    }});
    return r.execute("null-args", null, { timeoutMs: 2000 }).then(function (res) {
      return eq(res.status, "completed", "null args handled gracefully");
    });
  });

  async_("malformed-args-not-object", function () {
    var r = rt();
    r.register({ name: "scalar-args", execute: function (args) {
      return typeof args;
    }});
    return r.execute("scalar-args", "string-not-obj", { timeoutMs: 2000 }).then(function (res) {
      return eq(res.status, "completed", "string args handled gracefully (no crash)");
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Runner
  // ─────────────────────────────────────────────────────────────────────────

  function toolRuntimeTests(filter) {
    if (!global.AmiCorToolRuntime) {
      console.error("[toolRuntimeTests] AmiCorToolRuntime not found. Load tools.js first.");
      return Promise.resolve({ passed: 0, failed: 1, total: 1 });
    }

    console.group(
      "%c AmiCorToolRuntime Test Suite",
      "font-weight:bold;font-size:14px;color:#2196f3"
    );
    console.time("toolRuntimeTests:total");

    var passed = 0;
    var failed = 0;

    function processResults(results) {
      var flat = Array.isArray(results) ? results : [results];
      flat.forEach(function (r) {
        if (!r) return;
        if (r.ok) {
          console.log("  %c✓ " + r.desc, "color:#4caf50");
          passed++;
        } else {
          console.warn("  %c✗ " + r.desc, "color:#f44336");
          if (r.detail) console.warn("    " + String(r.detail));
          failed++;
        }
      });
    }

    // Run sync groups
    var syncPromises = SYNC_GROUPS
      .filter(function (g) { return !filter || g.name.indexOf(filter) !== -1; })
      .map(function (g) {
        console.group("%c ● " + g.name + " (sync)", "font-weight:bold");
        console.time(g.name);
        var raw;
        try { raw = g.run(); } catch (e) {
          raw = [{ ok: false, desc: "(threw)", detail: String(e) }];
        }
        processResults(Array.isArray(raw) ? raw : [raw]);
        console.timeEnd(g.name);
        console.groupEnd();
        return Promise.resolve();
      });

    // Run async groups sequentially to keep output readable
    var asyncFiltered = ASYNC_GROUPS.filter(function (g) {
      return !filter || g.name.indexOf(filter) !== -1;
    });

    return Promise.all(syncPromises).then(function () {
      return asyncFiltered.reduce(function (chain, g) {
        return chain.then(function () {
          console.group("%c ● " + g.name + " (async)", "font-weight:bold");
          console.time(g.name);
          return Promise.resolve()
            .then(function () { return g.run(); })
            .then(function (raw) {
              processResults(Array.isArray(raw) ? raw : [raw]);
            })
            .catch(function (e) {
              processResults([{ ok: false, desc: "(threw)", detail: String(e) }]);
            })
            .then(function () {
              console.timeEnd(g.name);
              console.groupEnd();
            });
        });
      }, Promise.resolve());
    }).then(function () {
      var total = passed + failed;
      console.timeEnd("toolRuntimeTests:total");
      var style = failed === 0
        ? "font-weight:bold;color:#4caf50"
        : "font-weight:bold;color:#f44336";
      console.log(
        "%c\n  Results: " + passed + "/" + total + " passed" +
        (failed > 0 ? ", " + failed + " FAILED" : " ✓"),
        style
      );
      console.groupEnd();
      return { passed: passed, failed: failed, total: total };
    });
  }

  global.toolRuntimeTests = toolRuntimeTests;

})(window);
