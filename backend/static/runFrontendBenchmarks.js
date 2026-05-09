#!/usr/bin/env node

"use strict";

const ProductExperience = require("./ux/productExperience.js");

function nowMs() {
  return Number(process.hrtime.bigint() / BigInt(1000000));
}

function bench(label, iterations, fn) {
  const t0 = nowMs();
  for (let i = 0; i < iterations; i++) fn(i);
  const total = nowMs() - t0;
  return {
    label,
    iterations,
    totalMs: total,
    avgMs: total / iterations,
    opsPerSec: iterations / Math.max(0.001, total / 1000),
  };
}

function format(rows) {
  const lines = [];
  lines.push("\n=== Frontend Benchmark Suite ===\n");
  lines.push("Batch                              Ops      Avg(ms)    Total(ms)    ops/s");
  lines.push("--------------------------------------------------------------------------");
  rows.forEach((r) => {
    lines.push(
      (r.label + "                              ").slice(0, 34) +
      String(r.iterations).padStart(8) +
      String(r.avgMs.toFixed(4)).padStart(12) +
      String(r.totalMs.toFixed(1)).padStart(13) +
      String(Math.round(r.opsPerSec)).padStart(9)
    );
  });
  lines.push("");
  return lines.join("\n");
}

function createStorage() {
  return {
    _data: {},
    getItem(k) { return this._data[k] || null; },
    setItem(k, v) { this._data[k] = String(v); },
    removeItem(k) { delete this._data[k]; },
  };
}

function main() {
  const storage = createStorage();
  const vault = ProductExperience.createConversationVault({ storage, namespace: "bench" });
  const workflows = ProductExperience.createWorkflowCenter({ storage, namespace: "bench" });

  for (let i = 0; i < 200; i++) {
    vault.appendMessage("user", "message " + i + " invoice and lead follow up", {});
    vault.appendMessage("ai", "response " + i + " with support workflow", {});
  }

  for (let i = 0; i < 60; i++) {
    workflows.saveTemplate({
      name: "Template " + i,
      prompt: "Do workflow " + i,
      actions: [{ type: "chat" }, { type: "search" }],
    });
  }

  const templates = workflows.listTemplates();

  const results = [];
  results.push(bench("conversation-search", 1200, function (i) {
    vault.search(i % 2 === 0 ? "invoice" : "support");
  }));

  results.push(bench("conversation-export", 900, function () {
    vault.exportState();
  }));

  results.push(bench("workflow-run", 1000, function (i) {
    const template = templates[i % templates.length];
    workflows.runTemplate(template.id, "benchmark run");
  }));

  results.push(bench("trust-snapshot", 3000, function (i) {
    ProductExperience.buildTrustSnapshot({
      diagnostics: { totalRequests: 100 + i, totalErrors: i % 5, avgLatency: 1000 + (i % 400), errorRate: i % 33 },
      monitor: { heartbeatOk: i % 11 !== 0, responseTimes: { avg: 900 + (i % 200) } },
    });
  }));

  console.log(format(results));
}

main();
