"use strict";

require.extensions[".jsx"] = require.extensions[".js"];

const { createAssistantController } = require("./assistant");
const ProductExperience = require("./ux/productExperience.js");
const {
  createConversationController,
  createConversationStore,
  createStreamingRenderer,
  buildWorkflowTimelineModel,
} = require("../../frontend/src/conversation");

function createMemoryStorage() {
  var data = {};
  return {
    getItem: function (key) { return data[key] || null; },
    setItem: function (key, value) { data[key] = String(value); },
    removeItem: function (key) { delete data[key]; },
  };
}

function createMockRuntime(options) {
  var config = Object.assign({ delayMs: 0, failTool: null }, options || {});
  var tools = [
    { name: "search-tool", type: "search", permissions: ["search"], metadata: { supportedTaskTypes: ["search", "generic"] } },
    { name: "io-tool", type: "io", permissions: ["io"], metadata: { supportedTaskTypes: ["io", "generic"] } },
  ];

  return {
    listTools: function () { return tools.slice(); },
    execute: async function (name, args) {
      if (config.delayMs > 0) {
        await new Promise(function (resolve) { setTimeout(resolve, config.delayMs); });
      }
      if (config.failTool && name === config.failTool) {
        throw new Error("forced tool failure");
      }
      return { ok: true, tool: name, args: args || {} };
    },
  };
}

function createMockMemory(options) {
  var config = Object.assign({ large: false, contextText: null }, options || {});
  return {
    async retrieve() {
      return { items: [{ id: "m1", content: "memory item" }] };
    },
    async assembleContext() {
      var context = config.contextText || (config.large ? new Array(6000).join("context ") : "compact context");
      return { context: context, compressed: { consumedTokens: Math.ceil(context.length / 4), overflow: config.large } };
    },
    async addWorkflowMemory() {
      return true;
    },
  };
}

async function runConversationUiTests() {
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

  function createConversationHarness(options) {
    var config = Object.assign({}, options || {});
    var assistantController = createAssistantController({
      runtime: config.runtime || createMockRuntime(config.runtimeOptions),
      memoryManager: config.memoryManager || createMockMemory(config.memoryOptions),
      permissions: ["search", "io"],
    });

    var store = createConversationStore({
      storageAdapter: createMemoryStorage(),
      persist: true,
      maxMessagesPerSession: 120,
      maxFeedEvents: 300,
    });

    var renderer = createStreamingRenderer({ flushIntervalMs: 1 });
    return createConversationController({
      assistantAdapter: assistantController,
      conversationStore: store,
      streamingRenderer: renderer,
      permissions: ["search", "io"],
    });
  }

  test("streaming interruptions are reflected in state", async function () {
    var controller = createConversationHarness({ runtimeOptions: { delayMs: 75 } });
    var runPromise = controller.submitGoal({
      id: "conv-interrupt",
      conversationId: "session-1",
      userGoal: "search weather then write summary",
    });

    await new Promise(function (resolve) { setTimeout(resolve, 10); });
    var cancel = controller.cancelResponse("user-cancel");
    var result = await runPromise;

    ok(cancel.cancelled, "cancel response succeeded");
    ok(result.result.status === "interrupted", "assistant status is interrupted");
  });

  test("workflow rendering model exposes graph and progress", async function () {
    var model = buildWorkflowTimelineModel({
      status: "completed",
      snapshot: {
        tasks: [
          { id: "a", type: "search", status: "completed", dependencies: [], retries: { attempted: 0 } },
          { id: "b", type: "io", status: "completed", dependencies: ["a"], retries: { attempted: 1 } },
        ],
      },
    });

    ok(model.nodes.length === 2, "timeline contains nodes");
    ok(model.edges.length === 1, "timeline contains dependency edges");
    ok(model.progressPercent === 100, "timeline progress reaches 100 percent");
  });

  test("rapid token updates do not lose rendered text", async function () {
    var renderer = createStreamingRenderer({ flushIntervalMs: 0 });
    for (var i = 0; i < 500; i++) {
      renderer.appendToken("t" + i + " ");
    }
    var text = renderer.finalize();
    ok(text.indexOf("t0") >= 0 && text.indexOf("t499") >= 0, "renderer preserved rapid token stream");
  });

  test("state desync recovery forces terminal state safely", async function () {
    var controller = createConversationHarness();
    await controller.submitGoal({
      id: "conv-desync",
      conversationId: "session-2",
      userGoal: "search docs",
    });

    controller.store.setAssistantState("not-real", {});
    var recovered = controller.store.recoverFromDesync({ forceTerminal: true, reason: "test-desync" });
    ok(recovered.assistantState === "interrupted" || recovered.assistantState === "failed", "desync recovery repaired state");
  });

  test("cancellation propagation records workflow cancel event", async function () {
    var controller = createConversationHarness({ runtimeOptions: { delayMs: 50 } });
    var runPromise = controller.submitGoal({
      id: "conv-cancel-workflow",
      conversationId: "session-3",
      userGoal: "search and summarize",
    });

    await new Promise(function (resolve) { setTimeout(resolve, 8); });
    var cancelled = controller.cancelWorkflow("cancel-workflow");
    var result = await runPromise;

    ok(cancelled.cancelled, "cancel workflow succeeded");
    ok(result.result.status === "interrupted", "workflow cancellation propagated to result state");
  });

  test("large conversation handling trims history deterministically", async function () {
    var controller = createConversationHarness();
    controller.store.createSession({ id: "big", title: "Big Session" });
    for (var i = 0; i < 1000; i++) {
      controller.store.appendMessage("user", "message " + i, {});
    }

    var snapshot = controller.snapshot().store;
    ok(snapshot.activeSession.messages.length <= 120, "store trimmed message history to configured limit");
  });

  test("what do you know about me uses stored memory context", async function () {
    var controller = createConversationHarness({
      memoryManager: createMockMemory({ contextText: "name=Riley | preferences=concise summaries | projects=Amicor rebuild" }),
    });

    var result = await controller.submitGoal({
      id: "conv-memory-known",
      conversationId: "session-memory-known",
      userGoal: "what do you know about me",
    });

    ok(result.result.status === "completed", "self-knowledge question completed");
    ok(/you|memory|remember/i.test(result.result.responseText), "response stays user-centered");
    ok(result.result.responseText.indexOf("short_term_memory") < 0, "response avoids short_term_memory label");
    ok(result.result.responseText.indexOf("long_term_memory") < 0, "response avoids long_term_memory label");
  });

  test("delete memory question explains clear-memory behavior", async function () {
    var controller = createConversationHarness();

    var result = await controller.submitGoal({
      id: "conv-delete-memory",
      conversationId: "session-delete-memory",
      userGoal: "how do I delete memory",
    });

    ok(result.result.status === "completed", "delete memory question completed");
    ok(result.result.responseText.indexOf("Clear Memory") >= 0, "response points to Clear Memory");
    ok(result.result.responseText.indexOf("recent and saved memory") >= 0, "response explains both memory layers naturally");
    ok(result.result.responseText.indexOf("short_term_memory") < 0, "response avoids short_term_memory label");
    ok(result.result.responseText.indexOf("long_term_memory") < 0, "response avoids long_term_memory label");
  });

  test("cached assistant responses are normalized before persistence", async function () {
    var storage = {
      _data: {},
      getItem: function (key) { return this._data[key] || null; },
      setItem: function (key, value) { this._data[key] = String(value); },
      removeItem: function (key) { delete this._data[key]; },
    };
    global.AmiCorMemoryManager = {
      POLICY_VIOLATION_CODE: "assistant-memory-policy-violation",
      loadMemory: function () {
        return { long_term_memory: { user_name: "Riley", preferences: [], likes_dislikes: [], goals: [], recurring_interests: [], active_projects: [], assistant_notes: [] } };
      },
      enforceAssistantVisibleResponse: function () {
        var error = new Error("policy violation");
        error.code = "assistant-memory-policy-violation";
        error.replacementText = "I remember what you've shared and will use it to personalize how I help.";
        throw error;
      },
    };
    try {
      var vault = ProductExperience.createConversationVault({ storage: storage, namespace: "cache-test" });
      var message = vault.appendMessage("ai", "I don't have any information about you specifically.", { tool: "openai" });
      ok(message.text.indexOf("I remember what you've shared") === 0, "cached assistant response replaced before persistence");
    } finally {
      delete global.AmiCorMemoryManager;
    }
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
  runConversationUiTests: runConversationUiTests,
};
