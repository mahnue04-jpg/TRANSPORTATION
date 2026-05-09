"use strict";

function getRuntime(runtimeOverride) {
  if (runtimeOverride) {
    return runtimeOverride;
  }
  if (typeof global !== "undefined" && global.AmiCorToolRuntime) {
    return global.AmiCorToolRuntime;
  }
  if (typeof window !== "undefined" && window.AmiCorToolRuntime) {
    return window.AmiCorToolRuntime;
  }
  return null;
}

function listTools(runtimeOverride) {
  var runtime = getRuntime(runtimeOverride);
  if (!runtime) {
    return [];
  }

  if (typeof runtime.listTools === "function") {
    return runtime.listTools() || [];
  }

  if (typeof runtime.getRegisteredTools === "function") {
    return runtime.getRegisteredTools() || [];
  }

  if (runtime._registry && typeof runtime._registry.list === "function") {
    return runtime._registry.list() || [];
  }

  return [];
}

function normalizeTool(toolDef) {
  if (!toolDef) {
    return null;
  }
  return {
    name: toolDef.name,
    permissions: Array.isArray(toolDef.permissions) ? toolDef.permissions.slice() : [],
    type: toolDef.type || null,
    metadata: toolDef.metadata || {},
  };
}

function hasPermissions(tool, executionPermissions) {
  var required = tool.permissions || [];
  var granted = Array.isArray(executionPermissions) ? executionPermissions : [];
  for (var i = 0; i < required.length; i++) {
    if (granted.indexOf(required[i]) === -1) {
      return false;
    }
  }
  return true;
}

function selectToolForTask(task, options) {
  var config = options || {};
  var runtime = getRuntime(config.runtime);
  var tools = listTools(runtime).map(normalizeTool).filter(Boolean);

  if (tools.length === 0) {
    return {
      selectedTool: task.assignedTool || null,
      valid: !!task.assignedTool,
      reason: task.assignedTool ? "runtime-unavailable-using-assigned-tool" : "no-tools-registered",
    };
  }

  var permissions = Array.isArray(config.permissions) ? config.permissions : [];

  if (task.assignedTool) {
    var direct = null;
    for (var i = 0; i < tools.length; i++) {
      if (tools[i].name === task.assignedTool) {
        direct = tools[i];
        break;
      }
    }

    if (!direct) {
      return { selectedTool: null, valid: false, reason: "assigned-tool-not-found" };
    }

    if (!hasPermissions(direct, permissions)) {
      return { selectedTool: null, valid: false, reason: "assigned-tool-permission-denied" };
    }

    return { selectedTool: direct.name, valid: true, reason: "assigned-tool" };
  }

  var ranked = [];
  for (var j = 0; j < tools.length; j++) {
    if (!hasPermissions(tools[j], permissions)) {
      continue;
    }

    var score = 0;
    if (tools[j].type && tools[j].type === task.type) {
      score += 5;
    }
    if (tools[j].name && tools[j].name.indexOf(task.type) >= 0) {
      score += 3;
    }
    if (tools[j].metadata && tools[j].metadata.supportedTaskTypes && tools[j].metadata.supportedTaskTypes.indexOf(task.type) >= 0) {
      score += 4;
    }
    ranked.push({ tool: tools[j], score: score });
  }

  ranked.sort(function (a, b) {
    if (b.score !== a.score) {
      return b.score - a.score;
    }
    return a.tool.name.localeCompare(b.tool.name);
  });

  if (ranked.length === 0) {
    return { selectedTool: null, valid: false, reason: "no-permitted-tool" };
  }

  return {
    selectedTool: ranked[0].tool.name,
    valid: true,
    reason: "ranked-match",
  };
}

module.exports = {
  getRuntime: getRuntime,
  listTools: listTools,
  selectToolForTask: selectToolForTask,
};
