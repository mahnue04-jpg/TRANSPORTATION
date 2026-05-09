"use strict";

const {
  createTaskPlanner,
  createWorkflowEngine,
  validateWorkflowPlan,
} = require("./planning");

function createMockRuntime() {
  var callCounts = Object.create(null);
  var tools = [
    { name: "search-tool", type: "search", permissions: ["search"], metadata: { supportedTaskTypes: ["search", "generic"] } },
    { name: "io-tool", type: "io", permissions: ["io"], metadata: { supportedTaskTypes: ["io", "generic"] } },
    { name: "fallback-tool", type: "fallback", permissions: ["io"], metadata: { supportedTaskTypes: ["fallback", "generic"] } },
    { name: "unstable-tool", type: "unstable", permissions: ["io"], metadata: { supportedTaskTypes: ["unstable"] } },
  ];

  async function execute(name, args, options) {
    callCounts[name] = (callCounts[name] || 0) + 1;

    if (options && options.signal && options.signal.aborted) {
      var abortError = new Error("aborted");
      abortError.code = "ABORT_ERR";
      throw abortError;
    }

    if (name === "unstable-tool") {
      var failUntil = args && typeof args.failUntilAttempt === "number" ? args.failUntilAttempt : 0;
      if (callCounts[name] <= failUntil) {
        throw new Error("simulated failure");
      }
    }

    if (args && args.delayMs) {
      await new Promise(function (resolve) { setTimeout(resolve, args.delayMs); });
    }

    if (args && args.forceError) {
      throw new Error(args.forceError);
    }

    return {
      ok: true,
      tool: name,
      args: args || {},
      callCount: callCounts[name],
      value: args && args.value !== undefined ? args.value : "ok",
    };
  }

  return {
    listTools: function () {
      return tools.slice();
    },
    execute: execute,
    getCallCounts: function () {
      return Object.assign({}, callCounts);
    },
  };
}

function createMockMemory() {
  return {
    async retrieve() {
      return { items: [{ id: "m1", content: "previous memory" }] };
    },
    async assembleContext() {
      return { context: "memory-context", compressed: { consumedTokens: 40 }, maxTokens: 300 };
    },
    async addWorkflowMemory() {
      return true;
    },
  };
}

async function runPlanningTests() {
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

  test("circular dependencies are rejected", async function () {
    var workflow = {
      id: "wf-cycle",
      tasks: [
        { id: "a", type: "search", dependencies: ["c"] },
        { id: "b", type: "io", dependencies: ["a"] },
        { id: "c", type: "io", dependencies: ["b"] },
      ],
    };

    var validation = validateWorkflowPlan(workflow, {
      permissions: ["search", "io"],
      runtime: createMockRuntime(),
      executionDepthLimit: 10,
      recursionLimit: 50,
      timeoutBudgetMs: 20000,
    });

    ok(!validation.valid, "cycle validation failed as expected");
    ok(validation.errors.some(function (item) { return item.code === "cycle-detected"; }), "cycle detection error is present");
  });

  test("failed tasks trigger fallback and continue", async function () {
    var runtime = createMockRuntime();
    var engine = createWorkflowEngine({ runtime: runtime, permissions: ["search", "io"] });

    var workflow = {
      id: "wf-fallback",
      tasks: [
        { id: "main", type: "unstable", assignedTool: "unstable-tool", retries: { max: 0 }, input: { forceError: "boom" }, fallbackTaskId: "fallback" },
        { id: "fallback", type: "fallback", assignedTool: "fallback-tool", dependencies: [], input: { value: "fallback-ok" } },
        { id: "tail", type: "io", assignedTool: "io-tool", dependencies: ["main"], allowPartialContinuation: true, input: { value: "tail" } },
      ],
      timeoutBudgetMs: 30000,
    };

    var result = await engine.executeWorkflow(workflow);
    var tasks = result.snapshot.tasks;
    var mainTask = tasks.find(function (task) { return task.id === "main"; });
    var tailTask = tasks.find(function (task) { return task.id === "tail"; });

    ok(result.status === "completed" || result.status === "failed", "workflow reached terminal status");
    ok(mainTask && mainTask.status === "completed", "main task recovered through fallback");
    ok(tailTask && (tailTask.status === "completed" || tailTask.status === "blocked"), "dependent task moved to terminal or blocked state");
  });

  test("retry storms are bounded by retry max", async function () {
    var runtime = createMockRuntime();
    var engine = createWorkflowEngine({ runtime: runtime, permissions: ["search", "io"] });

    var result = await engine.executeWorkflow({
      id: "wf-retries",
      tasks: [
        {
          id: "unstable",
          type: "unstable",
          assignedTool: "unstable-tool",
          retries: { max: 3, attempted: 0, backoffMs: 1 },
          input: { failUntilAttempt: 10 },
        },
      ],
    });

    ok(result.summary.retries === 3, "retry planner stopped at retry max");
    ok(result.snapshot.tasks[0].status === "failed", "task failed after retries exhausted");
  });

  test("cancellation propagates to dependent tasks", async function () {
    var runtime = createMockRuntime();
    var engine = createWorkflowEngine({ runtime: runtime, permissions: ["search", "io"] });

    var promise = engine.executeWorkflow({
      id: "wf-cancel",
      tasks: [
        { id: "first", type: "io", assignedTool: "io-tool", input: { delayMs: 50 } },
        { id: "second", type: "io", assignedTool: "io-tool", dependencies: ["first"], input: { delayMs: 50 } },
      ],
    });

    await new Promise(function (resolve) { setTimeout(resolve, 10); });
    var cancelResult = engine.cancelWorkflow("wf-cancel", "test-cancel");
    var result = await promise;

    ok(cancelResult.cancelled, "workflow cancellation call succeeded");
    ok(result.status === "cancelled", "workflow status is cancelled");
    ok(result.snapshot.tasks.some(function (task) { return task.status === "cancelled"; }), "at least one task is cancelled");
  });

  test("partial completion recovery allows continuation", async function () {
    var runtime = createMockRuntime();
    var engine = createWorkflowEngine({ runtime: runtime, permissions: ["search", "io"] });

    var result = await engine.executeWorkflow({
      id: "wf-partial",
      tasks: [
        { id: "root", type: "unstable", assignedTool: "unstable-tool", retries: { max: 0 }, input: { forceError: "fail" } },
        { id: "optional", type: "io", assignedTool: "io-tool", dependencies: ["root"], allowPartialContinuation: true, input: { value: "optional" } },
      ],
    });

    var optional = result.snapshot.tasks.find(function (task) { return task.id === "optional"; });
    ok(optional && (optional.status === "completed" || optional.status === "blocked"), "optional branch handled partial continuation");
  });

  test("concurrent workflows execute deterministically", async function () {
    var runtime = createMockRuntime();
    var engine = createWorkflowEngine({ runtime: runtime, permissions: ["search", "io"], maxConcurrentTasks: 1 });

    var flows = [];
    for (var i = 0; i < 4; i++) {
      flows.push(engine.executeWorkflow({
        id: "wf-concurrent-" + i,
        tasks: [
          { id: "a-" + i, type: "search", assignedTool: "search-tool", input: { value: i } },
          { id: "b-" + i, type: "io", assignedTool: "io-tool", dependencies: ["a-" + i], input: { value: i } },
        ],
      }));
    }

    var results = await Promise.all(flows);
    ok(results.length === 4, "all concurrent workflows returned");
    ok(results.every(function (item) { return item.status === "completed"; }), "all concurrent workflows completed");
  });

  test("workflow corruption recovery sanitizes invalid snapshots", async function () {
    var runtime = createMockRuntime();
    var engine = createWorkflowEngine({ runtime: runtime, permissions: ["search", "io"] });

    var recovered = engine.recoverWorkflow(
      {
        workflow: { status: "impossible" },
        tasks: [
          { id: "a", status: "nonsense", outputs: "broken" },
        ],
      },
      {
        id: "wf-recover",
        tasks: [
          { id: "a", type: "search", assignedTool: "search-tool" },
          { id: "b", type: "io", assignedTool: "io-tool", dependencies: ["a"] },
        ],
      }
    );

    ok(recovered.workflow.status === "pending", "invalid workflow status recovered to pending");
    ok(recovered.tasks.every(function (task) {
      return ["pending", "ready", "running", "blocked", "failed", "completed", "cancelled"].indexOf(task.status) >= 0;
    }), "all recovered tasks have valid status");
  });

  test("context-aware planner includes memory context", async function () {
    var runtime = createMockRuntime();
    var planner = createTaskPlanner({
      runtime: runtime,
      memoryManager: createMockMemory(),
      permissions: ["search", "io"],
    });

    var plan = await planner.plan({
      workflowId: "wf-plan",
      goal: "research then write",
      tasks: [
        { id: "search", type: "search", assignedTool: "search-tool" },
        { id: "write", type: "io", dependencies: ["search"], assignedTool: "io-tool" },
      ],
    });

    ok(plan.validation.valid, "planner output validates");
    ok(typeof plan.planningContext.memorySummary === "string", "memory summary is attached");
    ok(plan.visualization.nodes.length === 2, "visualization schema generated");
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

  return {
    passed: passed,
    failed: failed,
    total: passed + failed,
  };
}

module.exports = {
  runPlanningTests: runPlanningTests,
};
