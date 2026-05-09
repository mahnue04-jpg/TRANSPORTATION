"use strict";

const { createFilesystemTool } = require("./filesystemTool");
const { createDocumentTool } = require("./documentTool");
const { createHttpTool } = require("./httpTool");
const { createSearchTool } = require("./searchTool");
const { createProcessTool } = require("./processTool");

function createRealToolSuite(options) {
  const config = options || {};
  return {
    filesystemTool: createFilesystemTool(config.filesystem || config),
    documentTool: createDocumentTool(config.document || config),
    httpTool: createHttpTool(config.http || config),
    searchTool: createSearchTool(config.search || config),
    processTool: createProcessTool(config.process || config),
  };
}

function registerRealTools(runtime, options) {
  if (!runtime || typeof runtime.register !== "function") {
    throw new Error("registerRealTools requires an AmiCorToolRuntime instance");
  }
  const tools = createRealToolSuite(options);
  Object.keys(tools).forEach(function (key) {
    runtime.register(tools[key]);
  });
  return tools;
}

module.exports = {
  createRealToolSuite: createRealToolSuite,
  registerRealTools: registerRealTools,
  createFilesystemTool: createFilesystemTool,
  createDocumentTool: createDocumentTool,
  createHttpTool: createHttpTool,
  createSearchTool: createSearchTool,
  createProcessTool: createProcessTool,
};