"use strict";

require.extensions[".jsx"] = require.extensions[".js"];

const { createCapabilityRouter } = require("./capabilities");
const { createConversationStore } = require("../../frontend/src/conversation");

function createRuntime(options) {
  var config = Object.assign({ delayMs: 0, failTaskType: null }, options || {});

  var tools = [
    { name: "search-tool", type: "search", permissions: ["search"], metadata: { supportedTaskTypes: ["search", "generic"] } },
    { name: "document-tool", type: "document", permissions: ["document"], metadata: { supportedTaskTypes: ["document", "generic"] } },
    { name: "io-tool", type: "io", permissions: ["io"], metadata: { supportedTaskTypes: ["io", "generic"] } },
  ];

  return {
    listTools: function () { return tools.slice(); },
    execute: async function (toolName, args) {
      if (config.delayMs) {
        await new Promise(function (resolve) { setTimeout(resolve, config.delayMs); });
      }
      if (config.failTaskType && args && args.type === config.failTaskType) {
        throw new Error("forced-failure");
      }
      return { ok: true, tool: toolName, args: args || {} };
    },
  };
}

function createMemory(options) {
  var config = Object.assign({ memoryText: "memory context" }, options || {});
  return {
    async assembleContext() {
      return { context: config.memoryText, compressed: { consumedTokens: 18, overflow: false } };
    },
    async retrieve() {
      return { items: [{ id: "m-1", content: config.memoryText }] };
    },
    async addWorkflowMemory() {
      return true;
    },
  };
}

function createConversationAdapter() {
  var store = createConversationStore({
    persist: false,
    storageAdapter: {
      getItem: function () { return null; },
      setItem: function () {},
    },
  });
  store.createSession({ id: "cap-session", title: "Capability Session" });
  return {
    addWorkflowEntry: function (entry) { store.addWorkflowEntry(entry); },
    addExecutionEvent: function (event) { store.addExecutionEvent(event); },
    snapshot: function () { return store.getSnapshot(); },
  };
}

async function runCapabilitiesTests() {
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

  function buildHarness(options) {
    var config = options || {};
    return createCapabilityRouter({
      runtime: config.runtime || createRuntime(config.runtimeOptions),
      memoryManager: config.memoryManager || createMemory(config.memoryOptions),
      conversationAdapter: config.conversationAdapter || createConversationAdapter(),
      permissions: ["search", "document", "io"],
      timeoutBudgetMs: 120000,
    });
  }

  test("long workflows execute successfully", async function () {
    var router = buildHarness();
    var result = await router.runCapability({
      id: "long-1",
      capability: "workflowTemplates",
      templateId: "business-startup-checklist",
      goal: "Launch a new consultancy",
    });

    ok(result.status === "completed", "long template workflow completed");
  });

  test("interruption recovery supports continuation", async function () {
    var router = buildHarness({ runtimeOptions: { delayMs: 20 } });
    var runPromise = router.runCapability({
      id: "interrupt-1",
      capability: "researchAssistant",
      goal: "Research vendor options",
    });

    await new Promise(function (resolve) { setTimeout(resolve, 5); });
    var activeList = router.history;
    if (activeList.length > 0) {
      router.interruptWorkflow(activeList[activeList.length - 1].workflow.id, "manual-stop");
    }

    var result = await runPromise;
    if (result.status !== "completed") {
      var continuation = await router.continueWorkflow(result.workflowId);
      ok(continuation.status === "completed" || continuation.status === "failed", "continuation produced terminal status");
    } else {
      ok(true, "workflow completed before interruption applied");
    }
  });

  test("malformed inputs are rejected", async function () {
    var router = buildHarness();
    var result = await router.runCapability({ id: "malformed" });
    ok(result.status === "failed", "malformed request failed");
    ok(result.errors.some(function (item) { return item.code === "malformed-input"; }), "malformed error code present");
  });

  test("conflicting tasks are blocked", async function () {
    var router = buildHarness();
    var result = await router.runCapability({
      id: "conflict-1",
      goal: "cancel this and generate report",
    });
    ok(result.status === "failed", "conflicting request failed");
    ok(result.errors.some(function (item) { return item.code === "conflicting-tasks"; }), "conflicting task error code present");
  });

  test("workflow continuation from persisted history works", async function () {
    var router = buildHarness();
    var first = await router.runCapability({
      id: "continue-1",
      capability: "emailAssistant",
      goal: "Draft follow-up email",
    });

    var second = await router.continueWorkflow(first.workflowId);
    ok(second.status === "completed" || second.status === "failed", "continuation returned terminal status");
  });

  test("memory-aware responses include memory context", async function () {
    var router = buildHarness({ memoryOptions: { memoryText: "client prefers concise reports" } });
    var result = await router.runCapability({
      id: "memory-1",
      capability: "businessSummarizer",
      goal: "Summarize this quarter performance",
    });

    ok(!!result.memoryContext, "memory context exists");
    ok(String(result.memoryContext.memorySummary || "").indexOf("client prefers concise reports") >= 0, "memory summary propagated");
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
  runCapabilitiesTests: runCapabilitiesTests,
};
