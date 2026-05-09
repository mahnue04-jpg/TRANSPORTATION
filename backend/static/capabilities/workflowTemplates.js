"use strict";

const TEMPLATES = {
  "business-startup-checklist": {
    id: "business-startup-checklist",
    name: "Business Startup Checklist",
    description: "Plan setup activities for launching a new business initiative.",
    tasks: [
      { id: "market-research", type: "search", priority: 95 },
      { id: "legal-compliance", type: "document", priority: 92, dependencies: ["market-research"] },
      { id: "budget-planning", type: "io", priority: 88, dependencies: ["legal-compliance"] },
      { id: "launch-plan", type: "io", priority: 80, dependencies: ["budget-planning"] },
    ],
  },
  "proposal-drafting": {
    id: "proposal-drafting",
    name: "Proposal Drafting",
    description: "Prepare a structured proposal with context, solution, and action items.",
    tasks: [
      { id: "collect-requirements", type: "search", priority: 90 },
      { id: "draft-outline", type: "document", priority: 85, dependencies: ["collect-requirements"] },
      { id: "generate-proposal", type: "io", priority: 80, dependencies: ["draft-outline"] },
      { id: "review-risks", type: "io", priority: 75, dependencies: ["generate-proposal"] },
    ],
  },
  "invoice-workflow": {
    id: "invoice-workflow",
    name: "Invoice Workflow",
    description: "Generate and validate invoice-ready data with follow-up actions.",
    tasks: [
      { id: "collect-line-items", type: "document", priority: 90 },
      { id: "calculate-totals", type: "io", priority: 85, dependencies: ["collect-line-items"] },
      { id: "draft-invoice-email", type: "io", priority: 80, dependencies: ["calculate-totals"] },
    ],
  },
  "meeting-preparation": {
    id: "meeting-preparation",
    name: "Meeting Preparation",
    description: "Prepare agenda, briefing, and follow-up prompts before meetings.",
    tasks: [
      { id: "gather-context", type: "search", priority: 88 },
      { id: "draft-agenda", type: "io", priority: 85, dependencies: ["gather-context"] },
      { id: "identify-risks", type: "io", priority: 82, dependencies: ["draft-agenda"] },
      { id: "prepare-follow-ups", type: "io", priority: 78, dependencies: ["identify-risks"] },
    ],
  },
  "document-summarization": {
    id: "document-summarization",
    name: "Document Summarization",
    description: "Summarize long documents into concise business briefs.",
    tasks: [
      { id: "ingest-document", type: "document", priority: 90 },
      { id: "extract-highlights", type: "io", priority: 85, dependencies: ["ingest-document"] },
      { id: "write-summary", type: "io", priority: 82, dependencies: ["extract-highlights"] },
    ],
  },
  "action-item-extraction": {
    id: "action-item-extraction",
    name: "Action-item Extraction",
    description: "Extract and organize actionable follow-ups from notes or transcripts.",
    tasks: [
      { id: "parse-notes", type: "document", priority: 88 },
      { id: "extract-actions", type: "io", priority: 86, dependencies: ["parse-notes"] },
      { id: "assign-owners", type: "io", priority: 80, dependencies: ["extract-actions"] },
      { id: "schedule-follow-up", type: "io", priority: 75, dependencies: ["assign-owners"] },
    ],
  },
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function listWorkflowTemplates() {
  var ids = Object.keys(TEMPLATES).sort();
  return ids.map(function (id) {
    return { id: id, name: TEMPLATES[id].name, description: TEMPLATES[id].description, taskCount: TEMPLATES[id].tasks.length };
  });
}

function getWorkflowTemplate(templateId) {
  var template = TEMPLATES[String(templateId || "")];
  if (!template) {
    return null;
  }
  return clone(template);
}

function instantiateTemplate(templateId, vars) {
  var template = getWorkflowTemplate(templateId);
  if (!template) {
    return null;
  }
  var variables = vars || {};
  template.context = {
    variables: clone(variables),
    templateName: template.name,
  };
  return template;
}

module.exports = {
  listWorkflowTemplates: listWorkflowTemplates,
  getWorkflowTemplate: getWorkflowTemplate,
  instantiateTemplate: instantiateTemplate,
};
