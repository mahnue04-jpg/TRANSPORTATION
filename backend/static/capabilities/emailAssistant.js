"use strict";

function buildEmailWorkflow(input, context) {
  var payload = input.payload || {};
  return {
    capability: "emailAssistant",
    summary: "Prepared email drafting workflow with context and review passes",
    goal: input.goal || "Draft and refine business email",
    tasks: [
      { id: "email-context", type: "search", priority: 88, input: { audience: payload.audience || "stakeholder" } },
      { id: "email-draft", type: "io", priority: 86, dependencies: ["email-context"], input: { purpose: payload.purpose || "update" } },
      { id: "email-edit", type: "document", priority: 82, dependencies: ["email-draft"], input: { style: payload.style || "clear" } },
      { id: "email-final", type: "io", priority: 80, dependencies: ["email-edit"], input: { includeActionItems: !!payload.includeActionItems } },
    ],
    context: {
      memorySummary: context.memorySummary || "",
    },
  };
}

module.exports = {
  buildEmailWorkflow: buildEmailWorkflow,
};
