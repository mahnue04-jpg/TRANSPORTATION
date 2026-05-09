"use strict";

const CAPABILITY_TYPES = {
  documentWorkflow: "documentWorkflow",
  taskManager: "taskManager",
  schedulingAssistant: "schedulingAssistant",
  emailAssistant: "emailAssistant",
  reportGenerator: "reportGenerator",
  businessSummarizer: "businessSummarizer",
  workflowTemplates: "workflowTemplates",
  researchAssistant: "researchAssistant",
};

const CAPABILITY_STATUS = {
  pending: "pending",
  running: "running",
  interrupted: "interrupted",
  failed: "failed",
  completed: "completed",
};

function clone(value) {
  if (value === null || value === undefined) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(clone);
  }
  if (typeof value === "object") {
    var out = {};
    var keys = Object.keys(value);
    for (var i = 0; i < keys.length; i++) {
      out[keys[i]] = clone(value[keys[i]]);
    }
    return out;
  }
  return value;
}

function uid(prefix) {
  return String(prefix || "cap") + "-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
}

function createCapabilityRequest(input) {
  var source = input || {};
  return {
    id: String(source.id || uid("request")),
    capability: source.capability ? String(source.capability) : null,
    goal: String(source.goal || "").trim(),
    payload: clone(source.payload || {}),
    templateId: source.templateId ? String(source.templateId) : null,
    context: clone(source.context || {}),
    permissions: Array.isArray(source.permissions) ? source.permissions.slice() : [],
    timeoutBudgetMs: typeof source.timeoutBudgetMs === "number" ? Math.max(1000, source.timeoutBudgetMs) : 60000,
    conversationId: source.conversationId ? String(source.conversationId) : null,
    metadata: clone(source.metadata || {}),
  };
}

function createCapabilityWorkflow(input) {
  var source = input || {};
  return {
    id: String(source.id || uid("workflow")),
    capability: String(source.capability || "unknown"),
    goal: String(source.goal || ""),
    tasks: Array.isArray(source.tasks) ? clone(source.tasks) : [],
    templateId: source.templateId ? String(source.templateId) : null,
    context: clone(source.context || {}),
    status: CAPABILITY_STATUS.pending,
    createdAt: Date.now(),
  };
}

function createCapabilityResult(input) {
  var source = input || {};
  return {
    requestId: source.requestId || null,
    workflowId: source.workflowId || null,
    capability: source.capability || null,
    status: source.status || CAPABILITY_STATUS.failed,
    workflowResult: clone(source.workflowResult || null),
    summary: String(source.summary || ""),
    streamedChunks: Array.isArray(source.streamedChunks) ? source.streamedChunks.slice() : [],
    memoryContext: clone(source.memoryContext || null),
    persisted: !!source.persisted,
    errors: Array.isArray(source.errors) ? source.errors.slice() : [],
    startedAt: typeof source.startedAt === "number" ? source.startedAt : null,
    completedAt: typeof source.completedAt === "number" ? source.completedAt : Date.now(),
  };
}

function isCapabilityType(value) {
  return !!CAPABILITY_TYPES[String(value || "")];
}

module.exports = {
  CAPABILITY_TYPES: CAPABILITY_TYPES,
  CAPABILITY_STATUS: CAPABILITY_STATUS,
  cloneCapabilityValue: clone,
  createCapabilityRequest: createCapabilityRequest,
  createCapabilityWorkflow: createCapabilityWorkflow,
  createCapabilityResult: createCapabilityResult,
  isCapabilityType: isCapabilityType,
};
