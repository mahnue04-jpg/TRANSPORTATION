#!/usr/bin/env node

"use strict";

require.extensions[".jsx"] = require.extensions[".js"];

const { createAssistantController } = require("./assistant");
const { createConversationController, createConversationStore, createStreamingRenderer } = require("../../frontend/src/conversation");
const { createBenchmarkCollector, formatBenchmarkReport } = require("./conversationUiBenchmarks");

function createMemoryStorage() {
  var data = {};
  return {
    getItem: function (key) { return data[key] || null; },
    setItem: function (key, value) { data[key] = String(value); },
  };
}

function createMockRuntime() {
  var tools = [
    { name: "search-tool", type: "search", permissions: ["search"], metadata: { supportedTaskTypes: ["search", "generic"] } },
    { name: "io-tool", type: "io", permissions: ["io"], metadata: { supportedTaskTypes: ["io", "generic"] } },
  ];

  return {
    listTools: function () { return tools.slice(); },
    execute: async function (name, args) {
      return { ok: true, tool: name, args: args || {} };
    },
  };
}

function createMockMemory() {
  return {
    async retrieve() { return { items: [] }; },
    async assembleContext() {
      return { context: "benchmark context", compressed: { consumedTokens: 12, overflow: false } };
    },
    async addWorkflowMemory() { return true; },
  };
}

function createController() {
  var assistant = createAssistantController({
    runtime: createMockRuntime(),
    memoryManager: createMockMemory(),
    permissions: ["search", "io"],
  });

  return createConversationController({
    assistantAdapter: assistant,
    conversationStore: createConversationStore({
      storageAdapter: createMemoryStorage(),
      persist: true,
      maxMessagesPerSession: 500,
      maxFeedEvents: 500,
    }),
    streamingRenderer: createStreamingRenderer({ flushIntervalMs: 1 }),
    permissions: ["search", "io"],
  });
}

async function runBatch(label, operations, executor) {
  var collector = createBenchmarkCollector(label);
  var tasks = [];

  for (var i = 0; i < operations; i++) {
    tasks.push((async function (index) {
      var start = Date.now();
      var result = await executor(index);
      collector.record(Date.now() - start, result.result ? result.result.status : "failed");
    })(i));
  }

  await Promise.all(tasks);
  return collector.finish(operations);
}

async function main() {
  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Conversation UI Benchmark Suite                                ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");

  var controller = createController();
  var summaries = [];

  summaries.push(await runBatch("conversation-streaming", 20, async function (index) {
    return controller.submitGoal({
      id: "bench-stream-" + index,
      conversationId: "bench-stream-session",
      userGoal: "search weather then write summary",
    });
  }));

  summaries.push(await runBatch("conversation-large-history", 15, async function (index) {
    var result = await controller.submitGoal({
      id: "bench-history-" + index,
      conversationId: "bench-history-session",
      userGoal: "find climate news and summarize",
    });
    for (var k = 0; k < 50; k++) {
      controller.store.appendMessage("user", "history item " + k + " for run " + index, {});
    }
    return result;
  }));

  console.log(formatBenchmarkReport(summaries));
  process.exit(0);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error);
  process.exit(1);
});
