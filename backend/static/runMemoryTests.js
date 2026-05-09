#!/usr/bin/env node

"use strict";

const { runMemoryTests } = require("./memoryTests.js");

async function main() {
  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Memory Test Suite                                              ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");

  const results = await runMemoryTests();
  console.log("\n  ───────────────────────────────────────────────────────────────");
  console.log("  Results: " + results.passed + " passed, " + results.failed + " failed");
  console.log("  ───────────────────────────────────────────────────────────────\n");

  if (results.failed === 0) {
    console.log("  ✓ All memory tests passed!\n");
    process.exit(0);
  }

  console.log("  ✗ " + results.failed + " memory test(s) failed.\n");
  process.exit(1);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error);
  process.exit(1);
});