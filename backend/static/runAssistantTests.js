#!/usr/bin/env node

"use strict";

const { runAssistantTests } = require("./assistantTests");

async function main() {
  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Assistant Test Suite                                           ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");

  var results = await runAssistantTests();

  console.log("\n  ───────────────────────────────────────────────────────────────");
  console.log("  Results: " + results.passed + " passed, " + results.failed + " failed");
  console.log("  ───────────────────────────────────────────────────────────────\n");

  if (results.failed === 0) {
    console.log("  ✓ All assistant tests passed!\n");
    process.exit(0);
  }

  console.log("  ✗ " + results.failed + " assistant test(s) failed.\n");
  process.exit(1);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error);
  process.exit(1);
});
