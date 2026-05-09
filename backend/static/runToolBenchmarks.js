#!/usr/bin/env node

"use strict";

const fs = require("fs");
const path = require("path");

const globalObj = globalThis;
globalObj.window = globalThis;

if (!globalObj.console.group) {
  globalObj.console.group = function () {};
}
if (!globalObj.console.groupEnd) {
  globalObj.console.groupEnd = function () {};
}

function loadScript(filePath) {
  const code = fs.readFileSync(filePath, "utf8");
  new Function(code).call(globalObj);
}

const staticDir = __dirname;
const runtimeDir = path.join(staticDir, "runtime");

["errors.js", "lifecycle.js", "events.js", "registry.js", "validator.js", "permissions.js", "metrics.js", "streaming.js", "runtime.js"].forEach(function (moduleFile) {
  loadScript(path.join(runtimeDir, moduleFile));
});
loadScript(path.join(staticDir, "tools.js"));

const { registerRealTools } = require("./tools/index.js");
const { createBenchmarkCollector, formatBenchmarkReport } = require("./toolBenchmarks/index.js");
const fsPromises = require("fs/promises");
const os = require("os");

async function createBenchmarkRuntime(overrides) {
  const sandboxRoot = await fsPromises.mkdtemp(path.join(os.tmpdir(), "amicore-bench-"));
  const runtime = globalObj.AmiCorToolRuntime.createRuntime();
  const defaults = {
    filesystem: { rootDir: sandboxRoot },
    document: { rootDir: sandboxRoot },
    search: { rootDir: sandboxRoot },
    process: { cwd: sandboxRoot, allowlist: ["node"] },
    http: {
      allowlist: ["example.com"],
      transport: async function (parsedUrl) {
        return {
          statusCode: 200,
          headers: { "content-type": "text/plain" },
          body: "benchmark:" + parsedUrl.pathname,
        };
      },
    },
  };
  const overrideConfig = overrides || {};
  const config = {
    filesystem: Object.assign({}, defaults.filesystem, overrideConfig.filesystem || {}),
    document: Object.assign({}, defaults.document, overrideConfig.document || {}),
    search: Object.assign({}, defaults.search, overrideConfig.search || {}),
    process: Object.assign({}, defaults.process, overrideConfig.process || {}),
    http: Object.assign({}, defaults.http, overrideConfig.http || {}),
  };
  registerRealTools(runtime, config);
  return { runtime: runtime, sandboxRoot: sandboxRoot, config: config };
}

async function cleanup(rootDir) {
  await fsPromises.rm(rootDir, { recursive: true, force: true }).catch(function () {});
}

async function runBatch(runtime, toolName, executions, permissions, argsFactory, onChunk) {
  const benchmark = createBenchmarkCollector(toolName);
  const promises = [];
  const startedAt = Date.now();

  const sampler = setInterval(function () {
    const metrics = runtime.getMetrics(toolName);
    benchmark.recordQueuePressure(metrics && metrics.activeCount ? metrics.activeCount : 0);
  }, 5);

  for (let index = 0; index < executions; index++) {
    const args = argsFactory(index);
    const started = Date.now();
    promises.push(
      runtime.execute(toolName, args, {
        permissions: permissions,
        onChunk: onChunk
          ? function (chunk) {
              const size = Buffer.byteLength(String(chunk));
              benchmark.recordStreaming(1, size);
              onChunk(chunk, index);
            }
          : function (chunk) {
              const size = Buffer.byteLength(String(chunk));
              benchmark.recordStreaming(1, size);
            },
      }).then(function (result) {
        benchmark.recordLatency(Date.now() - started);
        return result;
      })
    );
  }

  const results = await Promise.all(promises);
  clearInterval(sampler);

  const failures = results.filter(function (result) {
    return !result || result.status !== "completed";
  });
  if (failures.length > 0) {
    throw new Error(toolName + " benchmark had " + failures.length + " failed execution(s)");
  }

  const summary = benchmark.finish(executions);
  summary.totalWallTimeMs = Date.now() - startedAt;
  return summary;
}

async function main() {
  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Real Tool Benchmark Suite                                      ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");

  const summaries = [];
  const fsRuntime = await createBenchmarkRuntime();
  try {
    await fsPromises.mkdir(path.join(fsRuntime.sandboxRoot, "docs"), { recursive: true });
    summaries.push(
      await runBatch(
        fsRuntime.runtime,
        "filesystemTool",
        40,
        ["filesystem:use", "filesystem:write"],
        function (index) {
          return { operation: "writeFile", path: "docs/file-" + index + ".txt", content: "payload-" + index };
        }
      )
    );
  } finally {
    await cleanup(fsRuntime.sandboxRoot);
  }

  const docRuntime = await createBenchmarkRuntime();
  try {
    await fsPromises.mkdir(path.join(docRuntime.sandboxRoot, "docs"), { recursive: true });
    await fsPromises.writeFile(path.join(docRuntime.sandboxRoot, "docs/large.md"), Array.from({ length: 120 }, function (_, i) { return "Line " + i + " benchmark text."; }).join("\n"), "utf8");
    summaries.push(
      await runBatch(
        docRuntime.runtime,
        "documentTool",
        30,
        ["document:use", "document:read"],
        function () {
          return { operation: "chunkDocument", path: "docs/large.md", chunkSize: 64 };
        },
        function () {}
      )
    );
  } finally {
    await cleanup(docRuntime.sandboxRoot);
  }

  const searchRuntime = await createBenchmarkRuntime();
  try {
    await fsPromises.mkdir(path.join(searchRuntime.sandboxRoot, "notes"), { recursive: true });
    await fsPromises.writeFile(path.join(searchRuntime.sandboxRoot, "notes/a.md"), "alpha beta alpha", "utf8");
    await fsPromises.writeFile(path.join(searchRuntime.sandboxRoot, "notes/b.txt"), "alpha gamma delta", "utf8");
    summaries.push(
      await runBatch(
        searchRuntime.runtime,
        "searchTool",
        25,
        ["search:use"],
        function () {
          return { query: "alpha", page: 1, pageSize: 2 };
        }
      )
    );
  } finally {
    await cleanup(searchRuntime.sandboxRoot);
  }

  const httpRuntime = await createBenchmarkRuntime({
    http: {
      allowlist: ["example.com"],
      transport: async function (parsedUrl) {
        return { statusCode: 200, headers: {}, body: "benchmark:" + parsedUrl.pathname };
      },
    },
  });
  try {
    summaries.push(
      await runBatch(
        httpRuntime.runtime,
        "httpTool",
        20,
        ["http:use"],
        function (index) {
          return { url: "https://example.com/ping-" + index, retries: 0, timeoutMs: 100 };
        }
      )
    );
  } finally {
    await cleanup(httpRuntime.sandboxRoot);
  }

  const processRuntime = await createBenchmarkRuntime();
  try {
    summaries.push(
      await runBatch(
        processRuntime.runtime,
        "processTool",
        10,
        ["process:use", "process:spawn"],
        function () {
          return { command: "node", args: ["-e", "process.stdout.write('bench')"] };
        }
      )
    );
  } finally {
    await cleanup(processRuntime.sandboxRoot);
  }

  console.log(formatBenchmarkReport(summaries));
  process.exit(0);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error);
  process.exit(1);
});