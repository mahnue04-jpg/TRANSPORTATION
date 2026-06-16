#!/usr/bin/env node

"use strict";

const http = require("http");
const https = require("https");
const { URL } = require("url");

function createFetchPolyfill(baseUrl) {
  return function fetchPolyfill(path, options) {
    return new Promise(function (resolve, reject) {
      const url = new URL(path, baseUrl);
      const isHttps = url.protocol === "https:";
      const client = isHttps ? https : http;

      const requestOptions = {
        method: (options && options.method) || "GET",
        hostname: url.hostname,
        port: url.port || (isHttps ? 443 : 80),
        path: url.pathname + (url.search || ""),
        headers: (options && options.headers) || {},
      };

      const req = client.request(requestOptions, function (res) {
        let body = "";
        res.setEncoding("utf8");
        res.on("data", function (chunk) {
          body += chunk;
        });
        res.on("end", function () {
          resolve({
            status: res.statusCode || 0,
            json: async function () {
              try {
                return JSON.parse(body || "{}");
              } catch (_err) {
                return {};
              }
            },
          });
        });
      });

      req.on("error", reject);
      if (options && options.body) {
        req.write(options.body);
      }
      req.end();
    });
  };
}

async function main() {
  const baseUrl = process.env.AMICOR_TEST_BASE_URL || "http://127.0.0.1:8011";

  if (typeof global.fetch !== "function") {
    global.fetch = createFetchPolyfill(baseUrl);
  } else {
    const nativeFetch = global.fetch;
    global.fetch = function (path, options) {
      const maybeRelative = String(path || "");
      if (maybeRelative.startsWith("http://") || maybeRelative.startsWith("https://")) {
        return nativeFetch(path, options);
      }
      return nativeFetch(new URL(maybeRelative, baseUrl), options);
    };
  }

  require("./orchestrationRoutingTests.js");
  if (typeof global.orchestrationRoutingTests !== "function") {
    console.error("Routing test runner not found.");
    process.exit(1);
  }

  console.log("\n╔════════════════════════════════════════════════════════════════╗");
  console.log("║ Routing + Response Engine Tests                               ║");
  console.log("╚════════════════════════════════════════════════════════════════╝\n");
  console.log("Base URL:", baseUrl);

  const result = await global.orchestrationRoutingTests();
  if (!result || result.failed > 0) {
    process.exit(1);
  }
  process.exit(0);
}

main().catch(function (error) {
  console.error("FATAL ERROR:", error && error.message ? error.message : error);
  process.exit(1);
});
