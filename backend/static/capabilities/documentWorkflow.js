"use strict";

function buildDocumentWorkflow(input, context) {
  var payload = input.payload || {};
  var title = payload.title || "Document Workflow";

  return {
    capability: "documentWorkflow",
    summary: "Prepared document processing workflow for " + title,
    goal: input.goal || "Process and summarize document content",
    tasks: [
      { id: "doc-ingest", type: "document", priority: 92, input: { source: payload.source || "provided-document" } },
      { id: "doc-extract", type: "analysis", priority: 88, dependencies: ["doc-ingest"], input: { focus: payload.focus || "key points" } },
      { id: "doc-summarize", type: "io", priority: 84, dependencies: ["doc-extract"], input: { format: payload.format || "brief" } },
      { id: "doc-actions", type: "task", priority: 80, dependencies: ["doc-summarize"], input: { includeOwners: !!payload.includeOwners } },
    ],
    context: {
      memorySummary: context.memorySummary || "",
      retrievedMemories: context.retrievedMemories || [],
    },
  };
}

module.exports = {
  buildDocumentWorkflow: buildDocumentWorkflow,
};
