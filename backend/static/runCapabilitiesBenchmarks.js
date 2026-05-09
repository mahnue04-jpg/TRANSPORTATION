#!/usr/bin/env node

"use strict";

require.extensions[".jsx"] = require.extensions[".js"];

const { createCapabilityRouter } = require("./capabilities");
const { createConversationStore } = require("../../frontend/src/conversation");
const { createBenchmarkCollector, formatBenchmarkReport } = require("./capabilitiesBenchmarks");

function createRuntime() {
  var tools = [
    { name: "search-tool", type: "search", permissions: ["search"], metadata: { supportedTaskTypes: ["search", "generic"] } },
    { name: "document-tool", type: "document", permissions: ["document"], metadata: { supportedTaskTypes: ["document", "generic"] } },
    { name: "io-tool", type: "io", permissions: ["io"], metadata: { supportedTaskTypes: ["io", "generic"] } },
  ];

  return {
    listTools: function () { return tools.slice(); },
    execute: async function (name, args) {
      return { ok: true, tool: name, args: args || {} };
    },
  };
}

function createMemory() {
  return {
    async assembleContext() {
      return { context: "benchmark memory context", compressed: { consumedTokens: 10, overflow: false } };
    },
    async retrieve() {
      return { items: [] };
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
  store.createSession({ id: "bench-session", title: "Benchmark Session" });
  return {
    addWorkflowEntry: function (entry) { store.addWorkflowEntry(entry); },
    addExecutionEvent: function (event) { store.addExecutionEvent(event); },
  };
}

function createRouter() {
  return createCapabilityRouter({
    runtime: createRuntime(),
    memoryManager: createMemory(),
    conversationAdapter: createConversationAdapter(),
    permissions: ["search", "document", "io"],
    timeoutBudgetMs: 120000,
  });
}

async function runBatch(label, operations, executor) {
  var collector = createBenchmarkCollector(label);
  var tasks = [];

  for (var i = 0; i < operations; i++) {
    tasks.push((async function (index) {
      var started = Date.now();
      var result = await executor(index);
      collector.record(Date.now() - started, result.status);
    })(i));
  }

  await Promise.all(tasks);
  return collector.finish(operations);
}

async function main() {
  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Capability Benchmark Suite                                     ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");

  var router = createRouter();
  var summaries = [];

  summaries.push(await runBatch("capability-workflows", 30, async function (index) {
    return router.runCapability({
      id: "bench-cap-" + index,
      goal: "Research market and summarize options",
      capability: "researchAssistant",
    });
  }));

  summaries.push(await runBatch("template-workflows", 20, async function (index) {
    return router.runCapability({
      id: "bench-template-" + index,
      capability: "workflowTemplates",
      templateId: index % 2 === 0 ? "proposal-drafting" : "meeting-preparation",
      goal: "Prepare deliverable",
    });
  }));

  console.log(formatBenchmarkReport(summaries));
  process.exit(0);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error);
  process.exit(1);
});
