"use strict";

function buildBusinessSummaryWorkflow(input, context) {
  var payload = input.payload || {};
  return {
    capability: "businessSummarizer",
    summary: "Built business summary workflow with trend extraction and recommendations",
    goal: input.goal || "Summarize business performance and opportunities",
    tasks: [
      { id: "biz-ingest", type: "document", priority: 90, input: { inputs: payload.inputs || [] } },
      { id: "biz-trends", type: "io", priority: 86, dependencies: ["biz-ingest"], input: { horizons: payload.horizons || ["weekly", "monthly"] } },
      { id: "biz-summary", type: "io", priority: 82, dependencies: ["biz-trends"], input: { style: payload.style || "executive" } },
      { id: "biz-actions", type: "io", priority: 78, dependencies: ["biz-summary"], input: { includeOwners: true } },
    ],
    context: {
      memorySummary: context.memorySummary || "",
      retrievedMemories: context.retrievedMemories || [],
    },
  };
}

module.exports = {
  buildBusinessSummaryWorkflow: buildBusinessSummaryWorkflow,
};
