"use strict";

const { createSearchAdapter } = require("../toolAdapters");
const { createToolError, withLifecycle } = require("../toolAdapters/baseAdapter");

function createSearchTool(options) {
  const config = Object.assign({ rootDir: null, allowedExtensions: [".txt", ".md", ".json"] }, options || {});
  const adapter = createSearchAdapter(config);
  const lifecycle = Object.assign({ onBeforeExecute: null, onAfterExecute: null, onError: null, onFinally: null }, config.lifecycle || {});

  const execute = withLifecycle(lifecycle, async function (args, ctx) {
    if (!args.query || !String(args.query).trim()) {
      throw createToolError("invalid-query", "Search query is required");
    }
    return adapter.search(args, ctx);
  });

  return {
    name: "searchTool",
    description: "Local document search with pluggable index architecture",
    schema: {
      query: { type: "string", required: true },
      page: { type: "number", required: false, min: 1 },
      pageSize: { type: "number", required: false, min: 1 },
    },
    permissions: ["search:use"],
    timeout: 10000,
    retryable: false,
    execute: execute,
    metadata: {
      adapter: "search",
      capabilities: ["keyword-search", "paginated-results", "pluggable-index"],
      lifecycle: lifecycle,
      semanticReady: true,
      asyncSearch: true,
    },
  };
}

module.exports = { createSearchTool: createSearchTool };