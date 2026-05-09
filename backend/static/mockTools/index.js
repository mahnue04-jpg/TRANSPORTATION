/**
 * mockTools/index.js — Registry and setup for all mock tools
 *
 * Export: setupMockTools(runtime) → registers all mock tools
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  /**
   * Register all mock tools on a ToolRuntime instance
   * @param {ToolRuntime} runtime - The runtime instance
   * @returns {object} - Summary of registered tools
   */
  function setupMockTools(runtime) {
    if (!runtime || typeof runtime.register !== "function") {
      throw new Error("setupMockTools: invalid runtime");
    }

    var tools = [
      "delayTool",
      "streamTool",
      "failTool",
      "retryTool",
      "permissionTool",
      "largeChunkTool",
      "concurrentTool",
      "cancellationTool",
      "timeoutTool",
      "partialFailureTool"
    ];

    var registered = [];
    var failed = [];

    tools.forEach(function (toolKey) {
      var toolDef = global.AmiCorMockTools[toolKey];
      if (!toolDef) {
        failed.push({ toolKey: toolKey, reason: "not found" });
        return;
      }

      try {
        // Register tool with tools.js ToolRuntime format
        // Expects: register({ name, description, schema, permissions, execute, ...metadata })
        runtime.register({
          name: toolDef.name,
          description: toolDef.description || "",
          schema: toolDef.schema || {},
          permissions: toolDef.permissions || [],
          execute: toolDef.execute, // execute function
          timeout: toolDef.timeout || 30000,
          retryable: toolDef.retryable !== false,
          maxRetries: toolDef.maxRetries || 0
        });
        registered.push(toolDef.name);
      } catch (err) {
        failed.push({ toolKey: toolKey, reason: String(err) });
      }
    });

    return {
      registered: registered,
      failed: failed,
      total: tools.length,
      success: failed.length === 0
    };
  }

  global.AmiCorMockTools.setupMockTools = setupMockTools;
})(typeof global !== "undefined" ? global : globalThis);
