"use strict";

function buildMemoryContextModel(memoryContext) {
  var source = memoryContext || {};
  var summary = String(source.summary || source.context || "");
  var indicators = Array.isArray(source.indicators) ? source.indicators.slice() : [];

  if (source.overflow) {
    indicators.push("Context truncated to token budget");
  }

  if (!summary) {
    summary = "No contextual memory retrieved for this step.";
  }

  return {
    summary: summary,
    indicators: indicators,
    continuityHint: summary ? "Session continuity active" : "Session continuity limited",
  };
}

function MemoryContextPanel(props) {
  return {
    type: "MemoryContextPanel",
    model: buildMemoryContextModel(props && props.memoryContext),
  };
}

module.exports = {
  MemoryContextPanel: MemoryContextPanel,
  buildMemoryContextModel: buildMemoryContextModel,
};
