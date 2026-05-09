"use strict";

const { createDocumentAdapter } = require("../toolAdapters");
const { createToolError, withLifecycle } = require("../toolAdapters/baseAdapter");

function createDocumentTool(options) {
  const config = Object.assign({ rootDir: null, allowedExtensions: [".txt", ".md", ".json"] }, options || {});
  const adapter = createDocumentAdapter(config);
  const lifecycle = Object.assign({ onBeforeExecute: null, onAfterExecute: null, onError: null, onFinally: null }, config.lifecycle || {});

  const execute = withLifecycle(lifecycle, async function (args, ctx) {
    switch (args.operation) {
      case "readText":
        return adapter.readText(args, ctx);
      case "summarizeText":
        return adapter.summarizeText(args, ctx);
      case "extractMetadata":
        return adapter.extractMetadata(args, ctx);
      case "chunkDocument":
        return adapter.chunkDocument(args, ctx);
      default:
        throw createToolError("invalid-operation", "Unsupported document operation", {
          operation: args.operation,
          supported: ["readText", "summarizeText", "extractMetadata", "chunkDocument"],
        });
    }
  });

  return {
    name: "documentTool",
    description: "Document operations with text summarization and chunking support",
    schema: {
      operation: { type: "string", required: true, enum: ["readText", "summarizeText", "extractMetadata", "chunkDocument"] },
      path: { type: "string", required: false },
      text: { type: "string", required: false },
      chunkSize: { type: "number", required: false, min: 1 },
      maxSentences: { type: "number", required: false, min: 1 },
      maxChars: { type: "number", required: false, min: 1 },
    },
    permissions: ["document:use"],
    timeout: 10000,
    retryable: false,
    execute: execute,
    metadata: {
      adapter: "document",
      capabilities: ["readText", "summarizeText", "extractMetadata", "chunkDocument"],
      lifecycle: lifecycle,
      streaming: true,
      documentTypes: ["txt", "md", "json"],
    },
  };
}

module.exports = { createDocumentTool: createDocumentTool };