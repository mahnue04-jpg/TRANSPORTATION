#!/usr/bin/env node

"use strict";

const fs = require("fs/promises");
const os = require("os");
const path = require("path");

const { createMemoryManager } = require("./memory");
const { createBenchmarkCollector, formatBenchmarkReport } = require("./memoryBenchmarks");

async function createRuntime(rootName, options) {
  var root = await fs.mkdtemp(path.join(os.tmpdir(), rootName));
  var manager = createMemoryManager(Object.assign({ storagePath: path.join(root, "memory.json"), persist: true, sessionId: "bench-session" }, options || {}));
  return { manager: manager, root: root };
}

async function cleanup(root) {
  await fs.rm(root, { recursive: true, force: true }).catch(function () {});
}

async function runBatch(label, operations, executor) {
  var collector = createBenchmarkCollector(label);
  var start = Date.now();
  var tasks = [];
  for (let index = 0; index < operations; index++) {
    let opStart = Date.now();
    tasks.push(Promise.resolve()
      .then(function () { return executor(index); })
      .then(function (result) {
        collector.recordLatency(Date.now() - opStart);
        if (result && result.streamingUnits) {
          collector.recordStreaming(result.streamingUnits);
        }
        return result;
      }));
  }
  var results = await Promise.all(tasks);
  collector.recordQueuePressure(operations);
  var summary = collector.finish(operations);
  summary.wallTimeMs = Date.now() - start;
  summary.completed = results.length;
  return summary;
}

async function main() {
  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Memory Benchmark Suite                                         ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");

  var summaries = [];
  var runtime = await createRuntime("amicore-memory-bench-");
  try {
    summaries.push(await runBatch("memory-write", 50, async function (index) {
      await runtime.manager.addConversationMemory("conversation " + index + " alpha beta gamma", { frequency: 1 + (index % 3) });
      return { streamingUnits: 0 };
    }));

    summaries.push(await runBatch("memory-retrieve", 50, async function (index) {
      return runtime.manager.retrieve("alpha", { limit: 10 }).then(function (result) {
        return { streamingUnits: result.items.length };
      });
    }));

    summaries.push(await runBatch("memory-assemble", 25, async function () {
      return runtime.manager.assembleContext({ query: "alpha", maxTokens: 120 }).then(function () {
        return { streamingUnits: 1 };
      });
    }));
  } finally {
    await cleanup(runtime.root);
  }

  console.log(formatBenchmarkReport(summaries));
  process.exit(0);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error);
  process.exit(1);
});