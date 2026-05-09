"use strict";

const { createHttpAdapter } = require("../toolAdapters");
const { createToolError, withLifecycle } = require("../toolAdapters/baseAdapter");

function createHttpTool(options) {
  const config = Object.assign({ allowlist: [] }, options || {});
  const adapter = createHttpAdapter(config);
  const lifecycle = Object.assign({ onBeforeExecute: null, onAfterExecute: null, onError: null, onFinally: null }, config.lifecycle || {});

  const execute = withLifecycle(lifecycle, async function (args, ctx) {
    if (args.method && String(args.method).toUpperCase() !== "GET") {
      throw createToolError("method-not-allowed", "HTTP tool only supports GET requests initially");
    }
    return adapter.get(args, ctx);
  });

  return {
    name: "httpTool",
    description: "Allowlisted GET-only HTTP requests with timeout and retry support",
    schema: {
      url: { type: "string", required: true },
      method: { type: "string", required: false, enum: ["GET"] },
      timeoutMs: { type: "number", required: false, min: 1 },
      retries: { type: "number", required: false, min: 0 },
      streamChunks: { type: "boolean", required: false },
    },
    permissions: ["http:use"],
    timeout: 10000,
    retryable: true,
    maxRetries: 2,
    execute: execute,
    metadata: {
      adapter: "http",
      capabilities: ["get"],
      lifecycle: lifecycle,
      streaming: true,
      networkPolicy: { allowlist: config.allowlist.slice(), blockLocalhost: true, blockInternalNetwork: true },
    },
  };
}

module.exports = { createHttpTool: createHttpTool };