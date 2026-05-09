#!/usr/bin/env node

"use strict";

const { createAssistantController } = require("./assistant");
const { createBenchmarkCollector, formatBenchmarkReport } = require("./assistantBenchmarks");

function createMockRuntime() {
  var tools = [
    { name: "search-tool", type: "search", permissions: ["search"], metadata: { supportedTaskTypes: ["search", "generic"] } },
    { name: "io-tool", type: "io", permissions: ["io"], metadata: { supportedTaskTypes: ["io", "generic"] } },
  ];
  return {
    listTools: function () {
      return tools.slice();
    },
    execute: async function (name, args) {
      return { ok: true, tool: name, args: args || {} };
    },
  };
}

function createMockMemory() {
  return {
    async assembleContext() {
      return { context: "benchmark memory", compressed: { consumedTokens: 15, overflow: false } };
    },
    async retrieve() {
      return { items: [] };
    },
    async addWorkflowMemory() {
      return true;
    },
  };
}

async function runBatch(label, operations, executor) {
  var collector = createBenchmarkCollector(label);

  var tasks = [];
  for (var i = 0; i < operations; i++) {
    tasks.push((async function (index) {
      var startedAt = Date.now();
      var result = await executor(index);
      collector.recordLatency(Date.now() - startedAt);
      collector.recordResult(result.status);
    })(i));
  }

  await Promise.all(tasks);
  return collector.finish(operations);
}

async function main() {
  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Assistant Benchmark Suite                                      ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");

  var controller = createAssistantController({
    runtime: createMockRuntime(),
    memoryManager: createMockMemory(),
    permissions: ["search", "io"],
  });

  var summaries = [];

  summaries.push(await runBatch("assistant-simple-goals", 30, async function (index) {
    return controller.run({
      id: "bench-simple-" + index,
      conversationId: "bench-conv",
      userGoal: "search latest weather and write summary",
    });
  }));

  summaries.push(await runBatch("assistant-branch-goals", 20, async function (index) {
    return controller.run({
      id: "bench-branch-" + index,
      conversationId: "bench-conv-" + index,
      userGoal: "find climate headlines, then summarize and respond",
    });
  }));

  console.log(formatBenchmarkReport(summaries));
  process.exit(0);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error);
  process.exit(1);
});
