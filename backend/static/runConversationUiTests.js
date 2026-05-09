#!/usr/bin/env node

"use strict";

const { runConversationUiTests } = require("./conversationUiTests");

async function main() {
  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Conversation UI Integration Test Suite                         ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");

  var results = await runConversationUiTests();

  console.log("\n  ───────────────────────────────────────────────────────────────");
  console.log("  Results: " + results.passed + " passed, " + results.failed + " failed");
  console.log("  ───────────────────────────────────────────────────────────────\n");

  if (results.failed === 0) {
    console.log("  ✓ All conversation UI tests passed!\n");
    process.exit(0);
  }

  console.log("  ✗ " + results.failed + " conversation UI test(s) failed.\n");
  process.exit(1);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error);
  process.exit(1);
});
