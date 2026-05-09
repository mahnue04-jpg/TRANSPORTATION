#!/usr/bin/env node

/**
 * Quick test to verify mock tools work
 */

const fs = require("fs");
const path = require("path");

// Setup global
const global = globalThis;
global.window = globalThis;

// Load runtime
const runtimeModules = [
  "errors.js",
  "lifecycle.js",
  "events.js",
  "registry.js",
  "validator.js",
  "permissions.js",
  "metrics.js",
  "streaming.js",
  "runtime.js",
];

const staticDir = __dirname;
const runtimeDir = path.join(staticDir, "runtime");

runtimeModules.forEach((mod) => {
  const code = fs.readFileSync(path.join(runtimeDir, mod), "utf8");
  new Function(code).call(global);
});

// Load tools.js
const toolsCode = fs.readFileSync(path.join(staticDir, "tools.js"), "utf8");
new Function(toolsCode).call(global);

// Load mock tools
const mockToolsDir = path.join(staticDir, "mockTools");
const mockTools = [
  "delayTool.js",
  "streamTool.js",
  "failTool.js",
  "retryTool.js",
  "permissionTool.js",
  "largeChunkTool.js",
  "concurrentTool.js",
  "cancellationTool.js",
  "timeoutTool.js",
  "partialFailureTool.js",
  "index.js",
];

mockTools.forEach((tool) => {
  const toolPath = path.join(mockToolsDir, tool);
  if (fs.existsSync(toolPath)) {
    const code = fs.readFileSync(toolPath, "utf8");
    new Function(code).call(global);
  }
});

// Test
async function runQuickTest() {
  console.log("Testing mock tools...\n");

  const rt = global.AmiCorToolRuntime.createRuntime();
  console.log("Runtime created:", typeof rt);

  const setupResult = global.AmiCorMockTools.setupMockTools(rt);
  console.log("Setup result:", setupResult);
  console.log("Registered tools:", setupResult.registered);

  // Try a simple tool
  console.log("\n--- Testing delayTool ---");
  const delayResult = await rt.execute("mock-delay", { delayMs: 10 });
  console.log("Delay result:", JSON.stringify(delayResult, null, 2));

  // Try concurrent tool
  console.log("\n--- Testing concurrentTool ---");
  const concResult = await rt.execute("mock-concurrent", { workId: "test-1", durationMs: 10 });
  console.log("Concurrent result:", JSON.stringify(concResult, null, 2));

  // Try fail tool
  console.log("\n--- Testing failTool ---");
  const failResult = await rt.execute("mock-fail", {});
  console.log("Fail result:", JSON.stringify(failResult, null, 2));
}

runQuickTest().catch(console.error);
