#!/usr/bin/env node

"use strict";

const ProductExperience = require("./ux/productExperience.js");

let passed = 0;
let failed = 0;

function ok(name, cond) {
  if (cond) {
    passed++;
    console.log("  PASS  " + name);
  } else {
    failed++;
    console.error("  FAIL  " + name);
  }
}

function testConversationSearchAndPinning() {
  const storage = {
    _data: {},
    getItem(k) { return this._data[k] || null; },
    setItem(k, v) { this._data[k] = String(v); },
    removeItem(k) { delete this._data[k]; },
  };

  const vault = ProductExperience.createConversationVault({ storage, namespace: "ux-test" });
  vault.appendMessage("user", "Need invoice follow-up for ACME client", {});
  vault.appendMessage("ai", "I can build a sales follow-up workflow", {});
  vault.setPinned(true);

  const matches = vault.search("invoice");
  ok("conversation search finds messages", matches.length >= 1);
  ok("conversation can be pinned", vault.isPinned() === true);
  ok("conversation listing includes tags", vault.listConversations()[0].tags.length >= 1);
}

function testWorkflowCenter() {
  const storage = {
    _data: {},
    getItem(k) { return this._data[k] || null; },
    setItem(k, v) { this._data[k] = String(v); },
    removeItem(k) { delete this._data[k]; },
  };

  const center = ProductExperience.createWorkflowCenter({ storage, namespace: "wf-test" });
  const template = center.saveTemplate({
    name: "CRM Follow-up",
    prompt: "Draft client follow-up",
    actions: [{ type: "chat" }, { type: "email_draft" }],
  });

  const runResult = center.runTemplate(template.id, "run this");
  ok("workflow template saved", !!template.id);
  ok("workflow run succeeds", runResult.ok === true);
  ok("workflow run history captured", center.listRuns().length === 1);
}

function testTrustSnapshot() {
  const snapshot = ProductExperience.buildTrustSnapshot({
    diagnostics: { totalRequests: 10, totalErrors: 3, avgLatency: 2300, errorRate: 30 },
    monitor: { heartbeatOk: true },
  });

  ok("trust snapshot has health", ["healthy", "degraded", "critical"].indexOf(snapshot.health) !== -1);
  ok("trust snapshot returns hints", Array.isArray(snapshot.hints));
}

function testBusinessTagInference() {
  const tags = ProductExperience.inferBusinessTags("Create invoice and schedule follow-up meeting with lead");
  ok("infers finance tag", tags.indexOf("finance") !== -1);
  ok("infers crm or sales tag", tags.indexOf("crm") !== -1 || tags.indexOf("sales") !== -1);
}

function main() {
  console.log("\n=== UX Test Suite ===\n");
  testConversationSearchAndPinning();
  testWorkflowCenter();
  testTrustSnapshot();
  testBusinessTagInference();

  console.log("\n--- Results ---");
  console.log("Passed: " + passed);
  console.log("Failed: " + failed);

  if (failed > 0) process.exit(1);
}

main();
