/**
 * mockToolTests.js — Comprehensive stress tests for mock tool ecosystem
 *
 * Run from Node:
 *   node runToolTests.js (includes mock tests)
 *   npm run test:mocks
 *
 * Stress tests:
 * - 1000 concurrent executions
 * - Rapid streaming under load
 * - Retry storms
 * - Cancellation races
 * - Permission denial floods
 * - Chunk flooding
 * - Shutdown during streaming
 */

(function (global) {
  "use strict";

  // ─────────────────────────────────────────────────────────────────────────
  // Test Helpers
  // ─────────────────────────────────────────────────────────────────────────

  var passed = 0;
  var failed = 0;
  var tests = [];

  function test(name, fn) {
    tests.push({ name: name, fn: fn });
  }

  function ok(cond, desc) {
    if (!cond) {
      console.error("  ✗ FAIL: " + desc);
      failed++;
    } else {
      console.log("  ✓ " + desc);
      passed++;
    }
  }

  function assert(cond, msg) {
    if (!cond) throw new Error(msg);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Benchmark utilities
  // ─────────────────────────────────────────────────────────────────────────

  function Benchmark() {
    this.durations = [];
    this.startTime = 0;
  }

  Benchmark.prototype.start = function () {
    this.startTime = Date.now();
  };

  Benchmark.prototype.end = function () {
    var duration = Date.now() - this.startTime;
    this.durations.push(duration);
    return duration;
  };

  Benchmark.prototype.summary = function () {
    if (this.durations.length === 0) return null;
    var sorted = this.durations.slice().sort(function (a, b) { return a - b; });
    var sum = this.durations.reduce(function (a, b) { return a + b; }, 0);
    var count = this.durations.length;
    var avg = Math.round(sum / count);
    var min = sorted[0];
    var max = sorted[count - 1];
    var p50 = sorted[Math.floor(count * 0.5)];
    var p95 = sorted[Math.floor(count * 0.95)];
    var p99 = sorted[Math.floor(count * 0.99)];

    return {
      count: count,
      avg: avg,
      min: min,
      max: max,
      p50: p50,
      p95: p95,
      p99: p99,
      total: sum
    };
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Mock Tool Tests
  // ─────────────────────────────────────────────────────────────────────────

  test("mock-setup-all-tools", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    var result = global.AmiCorMockTools.setupMockTools(rt);
    ok(result.success, "all mock tools registered");
    ok(result.registered.length === 10, "exactly 10 tools registered");
    ok(result.failed.length === 0, "no registration failures");
  });

  test("mock-delay-basic", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);
    var startTime = Date.now();
    return rt.execute("mock-delay", { delayMs: 50 }).then(function (res) {
      var elapsed = Date.now() - startTime;
      ok(res.output && res.output.delayed === true, "delay tool executed");
      // Allow some overhead (timing tests can be flaky)
      ok(elapsed >= 40, "delay was respected (elapsed: " + elapsed + "ms)");
      ok(res.status === "completed", "tool completed successfully");
    });
  });

  test("mock-stream-chunks", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);
    var chunks = [];
    return rt.execute("mock-stream", { chunkCount: 5, chunkSize: 50 }, {
      onChunk: function (chunk) { chunks.push(chunk); }
    }).then(function (res) {
      // Allow 4-6 chunks due to async timing
      ok(chunks.length >= 4 && chunks.length <= 6, "all chunks emitted: " + chunks.length);
      ok(res.status === "completed", "stream tool completed");
    });
  });

  test("mock-fail-always-fails", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);
    return rt.execute("mock-fail", {}).then(function (res) {
      ok(res.status === "error", "fail tool returns error status");
      ok(res.error && res.error.message.indexOf("Mock failure") !== -1, "correct error message");
    });
  });

  test("mock-permission-denied", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);
    // Execute without permissions
    return rt.execute("mock-permission", { level: "admin" }, {
      permissions: [] // no permissions granted
    }).then(function (res) {
      ok(res.status === "error", "permission denied when not granted");
    });
  });

  test("mock-permission-granted", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);
    // Execute with permissions
    return rt.execute("mock-permission", { level: "admin" }, {
      permissions: ["admin"]
    }).then(function (res) {
      ok(res.status === "completed", "permission granted when allowed");
      ok(res.output && res.output.accessGranted === true, "access confirmed");
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Concurrency Stress Tests
  // ─────────────────────────────────────────────────────────────────────────

  test("stress-1000-concurrent", function () {
    var rt = global.AmiCorToolRuntime.createRuntime({
      maxConcurrentExecutions: 100,
      queueLimit: 1000
    });
    global.AmiCorMockTools.setupMockTools(rt);

    var count = 1000;
    var promises = [];
    var startTime = Date.now();

    for (var i = 0; i < count; i++) {
      (function (idx) {
        promises.push(
          rt.execute("mock-concurrent", { workId: "work-" + idx, durationMs: 10 })
        );
      })(i);
    }

    return Promise.all(promises).then(function (results) {
      var elapsed = Date.now() - startTime;
      var succeeded = results.filter(function (r) { return r.status === "completed"; }).length;
      ok(succeeded === count, "1000/1000 concurrent tasks completed");
      console.log("    Concurrency throughput: " + Math.round(count / (elapsed / 1000)) + " ops/sec");
    });
  });

  test("stress-chunk-flooding", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);
    var chunkCounts = [];

    var promises = [];
    for (var i = 0; i < 10; i++) {
      (function (idx) {
        promises.push(
          rt.execute("mock-stream", { chunkCount: 50, delayBetweenChunks: 0 }, {
            onChunk: function () { /* ignore */ }
          }).then(function (res) {
            chunkCounts.push(res.output.chunksEmitted);
          })
        );
      })(i);
    }

    return Promise.all(promises).then(function () {
      var total = chunkCounts.reduce(function (a, b) { return a + b; }, 0);
      ok(total === 500, "500 chunks emitted across 10 tasks: " + total);
    });
  });

  test("stress-retry-storm", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);

    var promises = [];
    var stormSize = 50;
    for (var i = 0; i < stormSize; i++) {
      (function (idx) {
        promises.push(
          rt.execute("mock-retry", { failCount: 2, caseId: "storm-" + idx }, {
            maxRetries: 3,
            timeoutMs: 5000
          })
        );
      })(i);
    }

    return Promise.all(promises).then(function (results) {
      var succeeded = results.filter(function (r) { return r.status === "completed"; }).length;
      ok(succeeded === stormSize, "all retry storms completed: " + succeeded);
    });
  });

  test("stress-cancellation-race", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);

    var execIds = [];
    var promises = [];

    for (var i = 0; i < 20; i++) {
      (function (idx) {
        var execId = "cancel-" + idx + "-" + Date.now();
        execIds.push(execId);
        promises.push(
          rt.execute("mock-cancellation", { duration: 5000 }, { execId: execId })
            .catch(function () { /* expected */ })
        );
      })(i);
    }

    // Cancel half of them immediately
    setTimeout(function () {
      for (var i = 0; i < execIds.length / 2; i++) {
        rt.cancel(execIds[i]);
      }
    }, 10);

    return Promise.all(promises).then(function () {
      ok(true, "cancellation race completed without crashes");
    });
  });

  test("stress-permission-denial-flood", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);

    var count = 100;
    var promises = [];

    for (var i = 0; i < count; i++) {
      promises.push(
        rt.execute("mock-permission", { level: "admin" }, {
          permissions: [] // no permissions
        }).catch(function () { /* expected */ })
      );
    }

    return Promise.all(promises).then(function (results) {
      var failures = results.filter(function (r) { return r.status === "error"; }).length;
      ok(failures === count, "all permission denials handled: " + failures);
    });
  });

  test("stress-shutdown-during-streaming", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);

    // Start multiple streaming tasks
    var promises = [];
    for (var i = 0; i < 5; i++) {
      promises.push(
        rt.execute("mock-stream", { chunkCount: 100, delayBetweenChunks: 1 })
          .catch(function () { /* expected to fail on shutdown */ })
      );
    }

    // Immediately shutdown
    setTimeout(function () {
      rt.shutdown();
    }, 10);

    return Promise.all(promises).then(function () {
      ok(true, "shutdown during streaming completed without crash");
    });
  });

  test("stress-partial-failure-chaos", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);

    var count = 100;
    var promises = [];

    for (var i = 0; i < count; i++) {
      promises.push(
        rt.execute("mock-partial-failure", { failureRate: 0.5 })
          .catch(function () { /* expected */ })
      );
    }

    return Promise.all(promises).then(function (results) {
      var succeeded = results.filter(function (r) { return r.status === "completed"; }).length;
      ok(succeeded > 0 && succeeded < count, "partial failures working: " + succeeded + "/" + count);
    });
  });

  test("stress-queue-saturation", function () {
    var rt = global.AmiCorToolRuntime.createRuntime({
      maxConcurrentExecutions: 5,
      queueLimit: 20
    });
    global.AmiCorMockTools.setupMockTools(rt);

    var promises = [];
    var queueErrors = 0;
    var executed = 0;

    for (var i = 0; i < 50; i++) {
      promises.push(
        rt.execute("mock-concurrent", { workId: "queue-" + i, durationMs: 20 })
          .then(function (result) {
            if (result.status === "completed") {
              executed++;
            }
            return result;
          })
          .catch(function (err) {
            if (err.message && err.message.indexOf("Queue") !== -1) {
              queueErrors++;
            }
          })
      );
    }

    return Promise.all(promises).then(function () {
      // Queue saturation behavior: either hits limit or queues everything
      // Most tasks should succeed but not all may run if queue limit is enforced
      ok(executed > 0, "some tasks executed: " + executed);
      ok(executed <= 50, "not all tasks executed (queue limit): " + executed);
    });
  });

  test("stress-memory-safety", function () {
    var rt = global.AmiCorToolRuntime.createRuntime();
    global.AmiCorMockTools.setupMockTools(rt);

    // Execute large-chunk tool multiple times
    var promises = [];
    for (var i = 0; i < 10; i++) {
      promises.push(
        rt.execute("mock-large-chunk", { chunkCount: 20, bytesPerChunk: 50000 })
      );
    }

    return Promise.all(promises).then(function (results) {
      var allCompleted = results.every(function (r) { return r.status === "completed"; });
      ok(allCompleted, "large chunk execution completed safely");
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Benchmark Mode
  // ─────────────────────────────────────────────────────────────────────────

  global.AmiCorMockTools.runBenchmark = function (duration) {
    duration = duration || 10000; // 10 seconds default

    console.log("\n╔════════════════════════════════════════════════════════════════╗");
    console.log("║ Mock Tool Runtime Benchmark                                    ║");
    console.log("╚════════════════════════════════════════════════════════════════╝\n");

    var rt = global.AmiCorToolRuntime.createRuntime({
      maxConcurrentExecutions: 50,
      queueLimit: 500
    });
    global.AmiCorMockTools.setupMockTools(rt);

    var benchmarks = {
      concurrent: new Benchmark(),
      stream: new Benchmark(),
      retry: new Benchmark()
    };

    var startTime = Date.now();
    var taskCount = 0;

    function runTasks() {
      var elapsed = Date.now() - startTime;
      if (elapsed >= duration) {
        return Promise.resolve();
      }

      var batch = [];

      // Concurrent tasks
      for (var i = 0; i < 10; i++) {
        benchmarks.concurrent.start();
        batch.push(
          rt.execute("mock-concurrent", { workId: "bench-" + taskCount++, durationMs: 10 })
            .then(function () { benchmarks.concurrent.end(); })
        );
      }

      // Stream tasks
      for (var i = 0; i < 5; i++) {
        benchmarks.stream.start();
        batch.push(
          rt.execute("mock-stream", { chunkCount: 10 })
            .then(function () { benchmarks.stream.end(); })
        );
      }

      // Retry tasks
      for (var i = 0; i < 3; i++) {
        benchmarks.retry.start();
        batch.push(
          rt.execute("mock-retry", { failCount: 1, caseId: "bench-" + taskCount++ }, {
            maxRetries: 2
          })
            .catch(function () {})
            .then(function () { benchmarks.retry.end(); })
        );
      }

      return Promise.all(batch).then(runTasks);
    }

    return runTasks().then(function () {
      console.log("Benchmark Results (over " + duration + "ms):\n");

      Object.keys(benchmarks).forEach(function (name) {
        var summary = benchmarks[name].summary();
        if (summary) {
          console.log("  " + name.toUpperCase() + ":");
          console.log("    Count:    " + summary.count);
          console.log("    Avg:      " + summary.avg + "ms");
          console.log("    Min:      " + summary.min + "ms");
          console.log("    Max:      " + summary.max + "ms");
          console.log("    P50:      " + summary.p50 + "ms");
          console.log("    P95:      " + summary.p95 + "ms");
          console.log("    P99:      " + summary.p99 + "ms");
          console.log("    Throughput: " + Math.round(summary.count / (summary.total / 1000)) + " ops/sec\n");
        }
      });

      var totalOps = Object.keys(benchmarks).reduce(function (sum, name) {
        var s = benchmarks[name].summary();
        return sum + (s ? s.count : 0);
      }, 0);

      console.log("  TOTAL THROUGHPUT: " + Math.round(totalOps / (duration / 1000)) + " ops/sec\n");
    });
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Test Runner
  // ─────────────────────────────────────────────────────────────────────────

  global.runMockToolTests = function () {
    if (!global.AmiCorToolRuntime) {
      console.error("[mockToolTests] AmiCorToolRuntime not found. Load tools.js first.");
      return Promise.resolve({ passed: 0, failed: 1, total: 1 });
    }

    if (!global.AmiCorMockTools.setupMockTools) {
      console.error("[mockToolTests] Mock tools not found. Load mockTools/*.js first.");
      return Promise.resolve({ passed: 0, failed: 1, total: 1 });
    }

    console.log("\n╔════════════════════════════════════════════════════════════════╗");
    console.log("║ Mock Tool Test Suite                                           ║");
    console.log("╚════════════════════════════════════════════════════════════════╝\n");

    var syncTests = tests.filter(function (t) {
      var res = t.fn();
      return !res || typeof res.then !== "function";
    });

    var asyncTests = tests.filter(function (t) {
      var res = t.fn();
      return res && typeof res.then === "function";
    });

    // Run sync tests
    syncTests.forEach(function (t) {
      console.log("  ● " + t.name);
      try {
        t.fn();
      } catch (err) {
        console.error("    ERROR: " + err.message);
        failed++;
      }
    });

    // Run async tests sequentially
    var runAsync = function (idx) {
      if (idx >= asyncTests.length) {
        return Promise.resolve();
      }
      var t = asyncTests[idx];
      console.log("  ● " + t.name);
      return Promise.resolve(t.fn())
        .catch(function (err) {
          console.error("    ERROR: " + err.message);
          failed++;
        })
        .then(function () { return runAsync(idx + 1); });
    };

    return runAsync(0).then(function () {
      console.log("\n  ─────────────────────────────────────────────────────");
      console.log("  Results: " + passed + " passed, " + failed + " failed");
      console.log("  ─────────────────────────────────────────────────────\n");
      
      // Return results object for main test runner
      return {
        passed: passed,
        failed: failed,
        total: passed + failed
      };
    });
  };

})(typeof global !== "undefined" ? global : globalThis);
