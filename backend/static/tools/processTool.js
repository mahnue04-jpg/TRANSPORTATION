"use strict";

const { createProcessAdapter } = require("../toolAdapters");
const { createToolError, withLifecycle } = require("../toolAdapters/baseAdapter");

function createProcessTool(options) {
  const config = Object.assign({ allowlist: ["node"] }, options || {});
  const adapter = createProcessAdapter(config);
  const lifecycle = Object.assign({ onBeforeExecute: null, onAfterExecute: null, onError: null, onFinally: null }, config.lifecycle || {});

  const execute = withLifecycle(lifecycle, async function (args, ctx) {
    if (!args.command) {
      throw createToolError("invalid-command", "A command is required");
    }
    return adapter.spawnProcess(args, ctx);
  });

  return {
    name: "processTool",
    description: "Sandboxed subprocess execution with strict command allowlisting",
    schema: {
      command: { type: "string", required: true },
      args: { type: "array", required: false },
      timeoutMs: { type: "number", required: false, min: 1 },
      cwd: { type: "string", required: false },
      input: { type: "string", required: false },
    },
    permissions: ["process:use"],
    timeout: 15000,
    retryable: false,
    execute: execute,
    metadata: {
      adapter: "process",
      capabilities: ["spawn-isolated-subprocess", "capture-stdout-stderr", "timeout", "cancellation"],
      lifecycle: lifecycle,
      sandboxed: true,
      allowShell: false,
      commandAllowlist: config.allowlist.slice(),
    },
  };
}

module.exports = { createProcessTool: createProcessTool };