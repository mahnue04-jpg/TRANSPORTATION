"use strict";

/**
 * deploymentValidator.js — Pre-deployment environment and config validation.
 */

const https = require("https");
const http = require("http");
const { URL } = require("url");

function createDeploymentValidator() {
  /**
   * validateEnvironment(config) — validate NODE_ENV, PORT, and other env constraints.
   * config: { env: Record<string, string> }
   */
  function validateEnvironment(config) {
    var env = (config && config.env) || process.env;
    var issues = [];
    var warnings = [];

    var nodeEnv = env["NODE_ENV"] || "";
    var validEnvs = ["dev", "development", "staging", "production", "test"];
    if (!nodeEnv) {
      warnings.push({ field: "NODE_ENV", message: "NODE_ENV is not set; defaulting to dev" });
    } else if (validEnvs.indexOf(nodeEnv.toLowerCase()) === -1) {
      issues.push({ field: "NODE_ENV", message: "Unrecognized NODE_ENV: " + nodeEnv });
    }

    var port = env["PORT"] ? parseInt(env["PORT"], 10) : null;
    if (port !== null && (isNaN(port) || port < 1 || port > 65535)) {
      issues.push({ field: "PORT", message: "Invalid PORT: " + env["PORT"] });
    }

    return { ok: issues.length === 0, issues, warnings };
  }

  /**
   * validateSecrets(secretsManager, requiredKeys) → { ok, issues, warnings }
   */
  function validateSecrets(secretsManager, requiredKeys) {
    var keys = requiredKeys || [];
    var issues = [];
    var warnings = [];

    keys.forEach(function (key) {
      if (!secretsManager.hasSecret(key)) {
        issues.push({ field: key, message: "Required secret is missing: " + key });
      }
    });

    return { ok: issues.length === 0, issues, warnings };
  }

  /**
   * validateConnectivity(urls) → Promise<{ ok, issues, warnings }>
   * Performs HEAD requests to each URL to validate reachability.
   */
  async function validateConnectivity(urls) {
    var urlList = urls || [];
    var issues = [];
    var warnings = [];

    await Promise.all(urlList.map(function (urlStr) {
      return new Promise(function (resolve) {
        var parsedUrl;
        try { parsedUrl = new URL(urlStr); } catch (_) {
          issues.push({ field: urlStr, message: "Invalid URL: " + urlStr });
          return resolve();
        }

        var transport = parsedUrl.protocol === "https:" ? https : http;
        var req = transport.request(
          {
            hostname: parsedUrl.hostname,
            port:     parsedUrl.port || (parsedUrl.protocol === "https:" ? 443 : 80),
            path:     parsedUrl.pathname + parsedUrl.search,
            method:   "HEAD",
          },
          function (res) {
            if (res.statusCode >= 500) {
              warnings.push({ field: urlStr, message: "Server returned " + res.statusCode });
            }
            res.resume();
            resolve();
          }
        );
        req.on("error", function (err) {
          issues.push({ field: urlStr, message: "Connectivity failed: " + (err.message || urlStr) });
          resolve();
        });
        req.setTimeout(5000, function () { req.destroy(); issues.push({ field: urlStr, message: "Timeout connecting to: " + urlStr }); resolve(); });
        req.end();
      });
    }));

    return { ok: issues.length === 0, issues, warnings };
  }

  /**
   * validateConfig(schema, config) — generic key/type validation.
   * schema: { required: string[], types: { key: 'string'|'number'|'boolean' } }
   */
  function validateConfig(schema, config) {
    var s = schema || {};
    var cfg = config || {};
    var issues = [];
    var warnings = [];

    (s.required || []).forEach(function (key) {
      var val = cfg[key];
      if (val === undefined || val === null || val === "") {
        issues.push({ field: key, message: "Required config key missing: " + key });
      }
    });

    var types = s.types || {};
    Object.keys(types).forEach(function (key) {
      if (key in cfg) {
        var expected = types[key];
        // eslint-disable-next-line valid-typeof
        if (typeof cfg[key] !== expected) {
          issues.push({ field: key, message: "Expected " + expected + " but got " + typeof cfg[key] + " for: " + key });
        }
      }
    });

    (s.validators || []).forEach(function (v) {
      if (v.key in cfg) {
        var result = v.validate(cfg[v.key]);
        if (result && !result.ok) issues.push({ field: v.key, message: result.message });
      }
    });

    return { ok: issues.length === 0, issues, warnings };
  }

  /**
   * generateReport(results) — aggregate multiple validation results into one report.
   */
  function generateReport(results) {
    var allIssues = [];
    var allWarnings = [];

    (results || []).forEach(function (r) {
      if (r && r.issues) allIssues = allIssues.concat(r.issues);
      if (r && r.warnings) allWarnings = allWarnings.concat(r.warnings);
    });

    return {
      ok:       allIssues.length === 0,
      issues:   allIssues,
      warnings: allWarnings,
      summary:  {
        issueCount:   allIssues.length,
        warningCount: allWarnings.length,
        readyToDeploy: allIssues.length === 0,
      },
    };
  }

  return {
    validateEnvironment,
    validateSecrets,
    validateConnectivity,
    validateConfig,
    generateReport,
  };
}

module.exports = { createDeploymentValidator };
