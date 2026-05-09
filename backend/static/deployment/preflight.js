"use strict";

const fs = require("fs");
const path = require("path");

function readIfExists(filePath) {
  try {
    if (!fs.existsSync(filePath)) return null;
    return fs.readFileSync(filePath, "utf8");
  } catch (_) {
    return null;
  }
}

function detectProjectRoot(fromDir) {
  var current = fromDir;
  for (var i = 0; i < 6; i++) {
    if (fs.existsSync(path.join(current, "package.json")) && fs.existsSync(path.join(current, "backend"))) {
      return current;
    }
    var parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return fromDir;
}

function validateCloudConfigs(rootDir) {
  var checks = [
    { name: "render", file: "render.yaml" },
    { name: "railway", file: "railway.toml" },
    { name: "fly", file: "fly.toml" },
    { name: "docker", file: "Dockerfile" },
    { name: "procfile", file: "backend/Procfile" },
  ];

  return checks.map(function (entry) {
    var full = path.join(rootDir, entry.file);
    return {
      name: entry.name,
      file: entry.file,
      ok: fs.existsSync(full),
    };
  });
}

function validateHealthEndpoints(rootDir) {
  var mainPath = path.join(rootDir, "backend", "app", "main.py");
  var content = readIfExists(mainPath) || "";

  return {
    hasLiveness: content.indexOf('@app.get("/api/health")') !== -1,
    hasReadiness: content.indexOf('@app.get("/api/health/detail")') !== -1,
    hasAppShell: content.indexOf('@app.get("/app")') !== -1,
  };
}

function validateStartupCommands(rootDir) {
  var procfile = readIfExists(path.join(rootDir, "backend", "Procfile")) || "";
  var dockerfile = readIfExists(path.join(rootDir, "Dockerfile")) || "";

  return {
    hasProcfileWebCommand: /web\s*:\s*/i.test(procfile),
    hasDockerEntrypoint: /CMD\s*\[|ENTRYPOINT\s*\[/i.test(dockerfile),
  };
}

function buildSslAndBackupGuidance() {
  return {
    ssl: [
      "Use provider-managed TLS termination (Render/Railway/Fly).",
      "Force HTTPS redirects at edge and app layer where possible.",
      "Set secure cookie flags for auth and session cookies.",
    ],
    backup: [
      "Run daily database backups with 7-day retention.",
      "Store backups in a separate region or provider bucket.",
      "Validate restore by running a weekly recovery drill.",
    ],
  };
}

function runDeploymentPreflight(options) {
  var opts = options || {};
  var rootDir = opts.rootDir || detectProjectRoot(process.cwd());

  var cloudConfigs = validateCloudConfigs(rootDir);
  var health = validateHealthEndpoints(rootDir);
  var startup = validateStartupCommands(rootDir);
  var guidance = buildSslAndBackupGuidance();

  var issues = [];
  cloudConfigs.forEach(function (cfg) {
    if (!cfg.ok) issues.push("Missing deployment config: " + cfg.file);
  });
  if (!health.hasLiveness) issues.push("Missing /api/health endpoint");
  if (!health.hasReadiness) issues.push("Missing /api/health/detail endpoint");
  if (!startup.hasProcfileWebCommand) issues.push("Missing web command in backend/Procfile");

  return {
    ok: issues.length === 0,
    rootDir: rootDir,
    cloudConfigs: cloudConfigs,
    health: health,
    startup: startup,
    guidance: guidance,
    issues: issues,
  };
}

module.exports = {
  runDeploymentPreflight,
  validateCloudConfigs,
  validateHealthEndpoints,
  validateStartupCommands,
  buildSslAndBackupGuidance,
};
