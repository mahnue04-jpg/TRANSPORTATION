"use strict";

function buildResearchWorkflow(input, context) {
  var payload = input.payload || {};
  return {
    capability: "researchAssistant",
    summary: "Prepared research workflow with source evaluation and synthesis",
    goal: input.goal || "Research a topic and deliver findings",
    tasks: [
      { id: "research-query", type: "search", priority: 92, input: { topic: payload.topic || input.goal || "topic" } },
      { id: "research-evidence", type: "io", priority: 88, dependencies: ["research-query"], input: { qualityThreshold: payload.qualityThreshold || "medium" } },
      { id: "research-synthesis", type: "document", priority: 84, dependencies: ["research-evidence"], input: { includeSources: true } },
      { id: "research-summary", type: "io", priority: 80, dependencies: ["research-synthesis"], input: { audience: payload.audience || "team" } },
    ],
    context: {
      memorySummary: context.memorySummary || "",
      continuityHint: "Research continuity enabled",
    },
  };
}

module.exports = {
  buildResearchWorkflow: buildResearchWorkflow,
};
