#!/usr/bin/env node

"use strict";

const { createWorkflowEngine } = require("./planning");
const { createBenchmarkCollector, formatBenchmarkReport } = require("./planningBenchmarks");

function createMockRuntime() {
  var tools = [
    { name: "search-tool", type: "search", permissions: ["search"], metadata: { supportedTaskTypes: ["search"] } },
    { name: "io-tool", type: "io", permissions: ["io"], metadata: { supportedTaskTypes: ["io", "generic"] } },
  ];

  return {
    listTools: function () {
      return tools.slice();
    },
    execute: async function (name, args) {
      return { tool: name, args: args || {}, ok: true };
    },
  };
}

async function runBatch(label, operationCount, executor) {
  var collector = createBenchmarkCollector(label);
  var tasks = [];

  for (var i = 0; i < operationCount; i++) {
    tasks.push((async function (index) {
      var startedAt = Date.now();
      await executor(index);
      collector.recordLatency(Date.now() - startedAt);
      collector.recordWorkflowCompleted();
    })(i));
  }

  collector.recordQueuePressure(operationCount);
  await Promise.all(tasks);
  return collector.finish(operationCount);
}

async function main() {
  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Planning Benchmark Suite                                       ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");

  var runtime = createMockRuntime();
  var engine = createWorkflowEngine({
    runtime: runtime,
    permissions: ["search", "io"],
    maxConcurrentTasks: 1,
  });

  var summaries = [];

  summaries.push(await runBatch("workflow-execution", 40, async function (index) {
    await engine.executeWorkflow({
      id: "bench-exec-" + index,
      tasks: [
        { id: "search-" + index, type: "search", assignedTool: "search-tool", input: { query: "q" + index } },
        { id: "write-" + index, type: "io", assignedTool: "io-tool", dependencies: ["search-" + index], input: { index: index } },
      ],
      timeoutBudgetMs: 30000,
    });
  }));

  summaries.push(await runBatch("workflow-branching", 25, async function (index) {
    await engine.executeWorkflow({
      id: "bench-branch-" + index,
      tasks: [
        { id: "root-" + index, type: "search", assignedTool: "search-tool" },
        { id: "left-" + index, type: "io", assignedTool: "io-tool", dependencies: ["root-" + index], allowPartialContinuation: true },
        { id: "right-" + index, type: "io", assignedTool: "io-tool", dependencies: ["root-" + index], allowPartialContinuation: true },
      ],
      timeoutBudgetMs: 30000,
    });
  }));

  console.log(formatBenchmarkReport(summaries));
  process.exit(0);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error);
  process.exit(1);
});
