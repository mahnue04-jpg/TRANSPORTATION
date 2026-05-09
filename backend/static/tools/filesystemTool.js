"use strict";

const { createFilesystemAdapter } = require("../toolAdapters");
const { createToolError, withLifecycle } = require("../toolAdapters/baseAdapter");

function createFilesystemTool(options) {
  const config = Object.assign({ rootDir: null, allowedExtensions: [".txt", ".md", ".json"] }, options || {});
  const adapter = createFilesystemAdapter(config);
  const lifecycle = Object.assign({ onBeforeExecute: null, onAfterExecute: null, onError: null, onFinally: null }, config.lifecycle || {});

  const execute = withLifecycle(lifecycle, async function (args, ctx) {
    switch (args.operation) {
      case "readFile":
        return adapter.readFile(args, ctx);
      case "writeFile":
        return adapter.writeFile(args, ctx);
      case "appendFile":
        return adapter.appendFile(args, ctx);
      case "listDirectory":
        return adapter.listDirectory(args, ctx);
      case "createDirectory":
        return adapter.createDirectory(args, ctx);
      case "deleteFile":
        return adapter.deleteFile(args, ctx);
      default:
        throw createToolError("invalid-operation", "Unsupported filesystem operation", {
          operation: args.operation,
          supported: ["readFile", "writeFile", "appendFile", "listDirectory", "createDirectory", "deleteFile"],
        });
    }
  });

  return {
    name: "filesystemTool",
    description: "Sandboxed filesystem operations for real tool execution",
    schema: {
      operation: { type: "string", required: true, enum: ["readFile", "writeFile", "appendFile", "listDirectory", "createDirectory", "deleteFile"] },
      path: { type: "string", required: false },
      content: { type: "string", required: false },
      chunkSize: { type: "number", required: false, min: 1 },
    },
    permissions: ["filesystem:use"],
    timeout: 15000,
    retryable: false,
    execute: execute,
    metadata: {
      adapter: "filesystem",
      capabilities: ["readFile", "writeFile", "appendFile", "listDirectory", "createDirectory", "deleteFile"],
      lifecycle: lifecycle,
      streaming: true,
      sandboxed: true,
      security: { pathTraversalProtection: true, extensionAllowlist: config.allowedExtensions.slice() },
    },
  };
}

module.exports = { createFilesystemTool: createFilesystemTool };