#!/usr/bin/env node

"use strict";

const path = require("path");
const { runDeploymentPreflight } = require("../deployment/preflight");

const rootDir = path.resolve(__dirname, "..", "..", "..");
const report = runDeploymentPreflight({ rootDir });

console.log("\n=== Deployment Preflight ===\n");
console.log("Root: " + report.rootDir);
console.log("Healthy: " + (report.ok ? "yes" : "no"));
console.log("\nCloud configs:");
report.cloudConfigs.forEach((cfg) => {
  console.log("- " + cfg.name + " (" + cfg.file + "): " + (cfg.ok ? "ok" : "missing"));
});
console.log("\nHealth endpoints:");
console.log("- /api/health: " + (report.health.hasLiveness ? "ok" : "missing"));
console.log("- /api/health/detail: " + (report.health.hasReadiness ? "ok" : "missing"));
console.log("\nStartup checks:");
console.log("- Procfile web command: " + (report.startup.hasProcfileWebCommand ? "ok" : "missing"));
console.log("- Docker command/entrypoint: " + (report.startup.hasDockerEntrypoint ? "ok" : "missing"));

if (report.issues.length) {
  console.log("\nIssues:");
  report.issues.forEach((issue) => console.log("- " + issue));
}

console.log("\nSSL guidance:");
report.guidance.ssl.forEach((item) => console.log("- " + item));
console.log("\nBackup guidance:");
report.guidance.backup.forEach((item) => console.log("- " + item));

process.exit(report.ok ? 0 : 1);
