#!/usr/bin/env node

/**
 * runToolTests.js — Node.js-compatible test harness
 *
 * Executes:
 *   - toolRuntimeTests() from toolRuntime.test.js
 *   - toolHardenTests() from toolRuntime.harden.test.js
 *
 * Usage:
 *   node backend/static/runToolTests.js
 *
 * Exit codes:
 *   0 = all tests passed
 *   1 = one or more tests failed
 */

const fs = require("fs");
const path = require("path");

// ─────────────────────────────────────────────────────────────────────────
// Setup: Global object and polyfills
// ─────────────────────────────────────────────────────────────────────────

// Use globalThis for Node.js
const global = globalThis;
global.window = globalThis;

// Polyfill console methods that browser console has but Node doesn't
if (!global.console.group) {
  global.console.group = function (...args) {
    console.log(...args);
  };
}
if (!global.console.groupEnd) {
  global.console.groupEnd = function () {};
}

// Polyfill console.time and console.timeEnd
const timers = {};
if (!global.console.time) {
  global.console.time = function (label) {
    timers[label] = Date.now();
  };
}
if (!global.console.timeEnd) {
  global.console.timeEnd = function (label) {
    const start = timers[label];
    if (start !== undefined) {
      const duration = Date.now() - start;
      console.log(label + ": " + duration + "ms");
      delete timers[label];
    }
  };
}

// Polyfill for styled console (strip ANSI codes for plain output)
global.console.log = (function (originalLog) {
  return function (...args) {
    // Process %c styled logs
    let result = [];
    for (let i = 0; i < args.length; i++) {
      if (typeof args[i] === "string" && args[i].indexOf("%c") === 0) {
        // Skip the format string and the style argument
        result.push(args[i].replace(/%c/g, ""));
        i++; // skip the style argument
      } else if (typeof args[i] === "string") {
        result.push(args[i]);
      } else {
        result.push(args[i]);
      }
    }
    return originalLog.apply(console, result);
  };
})(global.console.log);

global.console.warn = (function (originalWarn) {
  return function (...args) {
    let result = [];
    for (let i = 0; i < args.length; i++) {
      if (typeof args[i] === "string" && args[i].indexOf("%c") === 0) {
        result.push(args[i].replace(/%c/g, ""));
        i++;
      } else if (typeof args[i] === "string") {
        result.push(args[i]);
      } else {
        result.push(args[i]);
      }
    }
    return originalWarn.apply(console, result);
  };
})(global.console.warn);

// Polyfill for crypto.randomUUID
if (!global.crypto) {
  global.crypto = {};
}
if (!global.crypto.randomUUID) {
  global.crypto.randomUUID = function () {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  };
}

// ─────────────────────────────────────────────────────────────────────────
// Helper: Load a file and execute it in the current global scope
// ─────────────────────────────────────────────────────────────────────────

function loadScript(filePath) {
  try {
    const code = fs.readFileSync(filePath, "utf8");
    // Use Function constructor to execute in global scope
    new Function(code).call(global);
  } catch (err) {
    console.error("ERROR loading " + filePath + ":", err.message);
    throw err;
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Load runtime modules in dependency order
// ─────────────────────────────────────────────────────────────────────────

const staticDir = __dirname;
const runtimeDir = path.join(staticDir, "runtime");

console.log("Loading runtime modules...\n");

// Load modules in order of dependencies
const modules = [
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

modules.forEach((mod) => {
  const modPath = path.join(runtimeDir, mod);
  console.log("  ✓ Loading " + mod);
  loadScript(modPath);
});

// Load tools.js (main runtime compatibility layer)
console.log("  ✓ Loading tools.js");
loadScript(path.join(staticDir, "tools.js"));

console.log(""); // blank line

// ─────────────────────────────────────────────────────────────────────────
// Load test files
// ─────────────────────────────────────────────────────────────────────────

console.log("Loading test files...\n");

console.log("  ✓ Loading toolRuntime.test.js");
loadScript(path.join(staticDir, "toolRuntime.test.js"));

console.log("  ✓ Loading toolRuntime.harden.test.js");
loadScript(path.join(staticDir, "toolRuntime.harden.test.js"));

console.log(""); // blank line

// ─────────────────────────────────────────────────────────────────────────
// Run tests
// ─────────────────────────────────────────────────────────────────────────

async function runAllTests() {
  console.log("═══════════════════════════════════════════════════════════════════════════\n");

  const results = {
    runtimeTests: null,
    hardenTests: null,
  };

  // Run toolRuntimeTests
  console.log("\n╔════════════════════════════════════════════════════════════════════════════╗");
  console.log("║ Running: toolRuntimeTests                                                  ║");
  console.log("╚════════════════════════════════════════════════════════════════════════════╝\n");

  try {
    if (typeof global.toolRuntimeTests === "function") {
      results.runtimeTests = await global.toolRuntimeTests();
    } else {
      console.error("ERROR: toolRuntimeTests not found");
      results.runtimeTests = { passed: 0, failed: 1, total: 1 };
    }
  } catch (err) {
    console.error("ERROR running toolRuntimeTests:", err);
    results.runtimeTests = { passed: 0, failed: 1, total: 1 };
  }

  console.log("\n");

  // Run toolHardenTests
  console.log("╔════════════════════════════════════════════════════════════════════════════╗");
  console.log("║ Running: toolHardenTests                                                   ║");
  console.log("╚════════════════════════════════════════════════════════════════════════════╝\n");

  try {
    if (typeof global.toolHardenTests === "function") {
      results.hardenTests = await global.toolHardenTests();
    } else {
      console.error("ERROR: toolHardenTests not found");
      results.hardenTests = { passed: 0, failed: 1, total: 1 };
    }
  } catch (err) {
    console.error("ERROR running toolHardenTests:", err);
    results.hardenTests = { passed: 0, failed: 1, total: 1 };
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Summary
  // ─────────────────────────────────────────────────────────────────────────

  console.log("\n═══════════════════════════════════════════════════════════════════════════\n");
  console.log("TEST SUMMARY");
  console.log("─────────────────────────────────────────────────────────────────────────────\n");

  const totalPassed =
    (results.runtimeTests?.passed || 0) + (results.hardenTests?.passed || 0);
  const totalFailed =
    (results.runtimeTests?.failed || 0) + (results.hardenTests?.failed || 0);
  const totalTests = (results.runtimeTests?.total || 0) + (results.hardenTests?.total || 0);

  console.log("  toolRuntimeTests:  " + (results.runtimeTests?.passed || 0) + "/" + (results.runtimeTests?.total || 0) + " passed" +
    (results.runtimeTests?.failed ? " (" + results.runtimeTests.failed + " FAILED)" : ""));
  console.log("  toolHardenTests:   " + (results.hardenTests?.passed || 0) + "/" + (results.hardenTests?.total || 0) + " passed" +
    (results.hardenTests?.failed ? " (" + results.hardenTests.failed + " FAILED)" : ""));

  console.log("");
  console.log("  ──────────────────────────────────────────────────────────────────────");
  console.log("  TOTAL:             " + totalPassed + "/" + totalTests + " passed" +
    (totalFailed > 0 ? " (" + totalFailed + " FAILED)" : " ✓"));
  console.log("  ──────────────────────────────────────────────────────────────────────\n");

  if (totalFailed === 0) {
    console.log("  ✓ All tests passed!\n");
    process.exit(0);
  } else {
    console.log("  ✗ " + totalFailed + " test(s) failed.\n");
    process.exit(1);
  }
}

// Run tests
runAllTests().catch((err) => {
  console.error("FATAL ERROR:", err);
  process.exit(1);
});
