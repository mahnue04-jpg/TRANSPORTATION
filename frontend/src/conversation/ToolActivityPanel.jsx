"use strict";

function classifyTool(toolName) {
  var value = String(toolName || "").toLowerCase();
  if (value.indexOf("file") >= 0 || value.indexOf("filesystem") >= 0) {
    return "filesystem actions";
  }
  if (value.indexOf("search") >= 0 || value.indexOf("news") >= 0 || value.indexOf("weather") >= 0) {
    return "search operations";
  }
  if (value.indexOf("document") >= 0) {
    return "document processing";
  }
  return "workflow steps";
}

function buildToolActivityModel(entries) {
  var source = Array.isArray(entries) ? entries : [];
  var rows = [];

  for (var i = 0; i < source.length; i++) {
    rows.push({
      at: source[i].at || Date.now(),
      tool: source[i].tool || source[i].assignedTool || "unknown",
      actionType: classifyTool(source[i].tool || source[i].assignedTool),
      status: source[i].status || "completed",
      details: source[i].details || source[i].output || null,
    });
  }

  rows.sort(function (a, b) { return a.at - b.at; });
  return rows;
}

function ToolActivityPanel(props) {
  return {
    type: "ToolActivityPanel",
    rows: buildToolActivityModel(props && props.entries),
  };
}

module.exports = {
  ToolActivityPanel: ToolActivityPanel,
  buildToolActivityModel: buildToolActivityModel,
};
