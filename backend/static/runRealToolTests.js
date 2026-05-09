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
if (!globalObj.console.time) {
  const timers = {};
  globalObj.console.time = function (label) {
    timers[label] = Date.now();
  };
  globalObj.console.timeEnd = function (label) {
    if (timers[label]) {
      console.log(label + ": " + (Date.now() - timers[label]) + "ms");
      delete timers[label];
    }
  };
}

if (!globalObj.crypto) {
  globalObj.crypto = {};
}
if (!globalObj.crypto.randomUUID) {
  globalObj.crypto.randomUUID = function () {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (char) {
      const random = (Math.random() * 16) | 0;
      const value = char === "x" ? random : (random & 0x3) | 0x8;
      return value.toString(16);
    });
  };
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
const { runRealToolTests } = require("./realToolTests.js");

async function main() {
  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Real Tool Test Suite                                           ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");

  const results = await runRealToolTests({
    createRuntime: function (opts) {
      return globalObj.AmiCorToolRuntime.createRuntime(opts);
    },
    registerRealTools: registerRealTools,
  });

  console.log("\n  ───────────────────────────────────────────────────────────────");
  console.log("  Results: " + results.passed + " passed, " + results.failed + " failed");
  console.log("  ───────────────────────────────────────────────────────────────\n");

  if (results.failed === 0) {
    console.log("  ✓ All real tool tests passed!\n");
    process.exit(0);
  }

  console.log("  ✗ " + results.failed + " real tool test(s) failed.\n");
  process.exit(1);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error);
  process.exit(1);
});