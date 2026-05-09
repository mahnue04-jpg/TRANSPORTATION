"use strict";

const { createAssistantController, createResponseSynthesizer } = require("./assistant");

function createMockRuntime(options) {
  var config = Object.assign({ failFirst: 0, delayMs: 0 }, options || {});
  var counts = Object.create(null);
  var tools = [
    { name: "search-tool", type: "search", permissions: ["search"], metadata: { supportedTaskTypes: ["search", "generic"] } },
    { name: "io-tool", type: "io", permissions: ["io"], metadata: { supportedTaskTypes: ["io", "generic"] } },
  ];

  return {
    listTools: function () {
      return tools.slice();
    },
    execute: async function (name, args) {
      counts[name] = (counts[name] || 0) + 1;
      if (config.delayMs > 0) {
        await new Promise(function (resolve) { setTimeout(resolve, config.delayMs); });
      }
      if (name === "search-tool" && counts[name] <= config.failFirst) {
        throw new Error("search temporary failure");
      }
      return { ok: true, tool: name, args: args || {}, count: counts[name] };
    },
    counts: counts,
  };
}

function createMockMemory(options) {
  var config = Object.assign({ largeContext: false }, options || {});
  return {
    async assembleContext() {
      var payload = config.largeContext ? new Array(3000).join("memory ") : "short memory";
      return {
        context: payload,
        compressed: { consumedTokens: Math.ceil(payload.length / 4), overflow: config.largeContext },
      };
    },
    async retrieve() {
      return { items: [{ id: "m-1", content: "memory item" }] };
    },
    async addWorkflowMemory() {
      return true;
    },
  };
}

async function runAssistantTests() {
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

  test("malformed goals are rejected", async function () {
    var controller = createAssistantController({
      runtime: createMockRuntime(),
      memoryManager: createMockMemory(),
      permissions: ["search", "io"],
    });

    var result = await controller.run({ id: "req-malformed", conversationId: "c-malformed", userGoal: "   " });
    ok(result.status === "failed", "empty goal failed safely");
  });

  test("execution interruption propagates", async function () {
    var controller = createAssistantController({
      runtime: createMockRuntime({ delayMs: 80 }),
      memoryManager: createMockMemory(),
      permissions: ["search", "io"],
    });

    var runPromise = controller.run({
      id: "req-interrupt",
      conversationId: "c-interrupt",
      userGoal: "search weather then write summary",
    });

    await new Promise(function (resolve) { setTimeout(resolve, 10); });
    controller.interrupt("req-interrupt", "c-interrupt", "user-stop");

    var result = await runPromise;
    ok(result.status === "interrupted", "assistant run was interrupted");
  });

  test("invalid tool selection is blocked", async function () {
    var controller = createAssistantController({
      runtime: createMockRuntime(),
      memoryManager: createMockMemory(),
      permissions: ["io"],
    });

    var result = await controller.run({
      id: "req-invalid-tool",
      conversationId: "c-invalid-tool",
      userGoal: "search latest headlines",
    });

    ok(result.status === "failed", "invalid tool permission failed");
    ok(result.errors.some(function (item) {
      return item.code === "tool-permission-invalid" || item.code === "execution-failed" || item.code === "unsafe-workflow";
    }), "failure reason captured");
  });

  test("conflicting tasks are rejected", async function () {
    var controller = createAssistantController({
      runtime: createMockRuntime(),
      memoryManager: createMockMemory(),
      permissions: ["search", "io"],
    });

    var result = await controller.run({
      id: "req-conflict",
      conversationId: "c-conflict",
      userGoal: "cancel this and search for climate news",
    });

    ok(result.status === "failed", "conflicting intent request failed");
  });

  test("context overflow is handled deterministically", async function () {
    var controller = createAssistantController({
      runtime: createMockRuntime(),
      memoryManager: createMockMemory({ largeContext: true }),
      maxContextTokens: 80,
      permissions: ["search", "io"],
    });

    var result = await controller.run({
      id: "req-overflow",
      conversationId: "c-overflow",
      userGoal: "search current weather and write response",
    });

    ok(result.status === "completed", "overflow request completed");
    ok(result.responseText.indexOf("truncated") >= 0, "response includes overflow note");
  });

  test("response corruption is sanitized", async function () {
    var synthesizer = createResponseSynthesizer({ safetyGuardrails: { validateEvidence: function () { return { valid: true, issues: [] }; } } });
    var response = synthesizer.synthesize({
      context: { overflow: false, memoryContext: { context: "memo\u0001\u0002" } },
      execution: {
        workflowResult: {
          status: "completed",
          snapshot: {
            tasks: [
              { id: "t1", status: "completed", outputs: { text: "ok\u0000\u0003" } },
            ],
          },
          summary: { completedTasks: 1 },
        },
      },
    });

    ok(response.text.indexOf("\u0000") < 0, "control characters were removed from response");
  });

  test("multi-step execution recovery succeeds after transient failure", async function () {
    var unstableRuntime = createMockRuntime({ failFirst: 1 });
    var controller = createAssistantController({
      runtime: unstableRuntime,
      memoryManager: createMockMemory(),
      permissions: ["search", "io"],
    });

    var first = await controller.run({
      id: "req-recovery-1",
      conversationId: "c-recovery",
      userGoal: "search weather then write summary",
    });

    var second = await controller.run({
      id: "req-recovery-2",
      conversationId: "c-recovery",
      userGoal: "search weather then write summary",
    });

    ok(first.status === "failed" || first.status === "completed", "first run reached terminal status");
    ok(second.status === "completed", "second run recovered and completed");
  });

  for (var i = 0; i < tests.length; i++) {
    console.log("  ● " + tests[i].name);
    try {
      await tests[i].fn();
    } catch (error) {
      failed += 1;
      console.error("    ERROR: " + error.message);
    }
  }

  return { passed: passed, failed: failed, total: passed + failed };
}

module.exports = {
  runAssistantTests: runAssistantTests,
};
