"use strict";

function buildReportWorkflow(input, context) {
  var payload = input.payload || {};
  return {
    capability: "reportGenerator",
    summary: "Generated report workflow with data collection, analysis, and publishing",
    goal: input.goal || "Generate business report",
    tasks: [
      { id: "report-collect", type: "search", priority: 90, input: { sources: payload.sources || [] } },
      { id: "report-analyze", type: "io", priority: 86, dependencies: ["report-collect"], input: { metrics: payload.metrics || [] } },
      { id: "report-draft", type: "document", priority: 82, dependencies: ["report-analyze"], input: { sections: payload.sections || ["overview", "insights", "actions"] } },
      { id: "report-publish", type: "io", priority: 78, dependencies: ["report-draft"], input: { format: payload.format || "markdown" } },
    ],
    context: {
      memorySummary: context.memorySummary || "",
      continuityHint: "Report continuity enabled",
    },
  };
}

module.exports = {
  buildReportWorkflow: buildReportWorkflow,
};
