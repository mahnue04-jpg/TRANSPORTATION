"use strict";

const ASSISTANT_STATES = {
  idle: "idle",
  interpreting: "interpreting",
  planning: "planning",
  executing: "executing",
  waiting: "waiting",
  responding: "responding",
  interrupted: "interrupted",
  failed: "failed",
  completed: "completed",
};

const VALID_ASSISTANT_STATES = Object.keys(ASSISTANT_STATES);

function uid(prefix) {
  return String(prefix || "assistant") + "-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
}

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

function createExecutionRequest(input) {
  var source = input || {};
  return {
    id: String(source.id || uid("request")),
    conversationId: source.conversationId ? String(source.conversationId) : uid("conversation"),
    userGoal: String(source.userGoal || "").trim(),
    context: clone(source.context || {}),
    permissions: Array.isArray(source.permissions) ? source.permissions.slice() : [],
    maxDepth: typeof source.maxDepth === "number" ? Math.max(1, source.maxDepth) : 8,
    timeoutBudgetMs: typeof source.timeoutBudgetMs === "number" ? Math.max(1, source.timeoutBudgetMs) : 45000,
    allowStreaming: source.allowStreaming !== false,
    metadata: clone(source.metadata || {}),
  };
}

function createReasoningStep(type, message, details) {
  return {
    at: Date.now(),
    type: String(type || "event"),
    message: String(message || ""),
    details: clone(details || {}),
  };
}

function createAssistantResult(input) {
  var source = input || {};
  return {
    requestId: source.requestId || null,
    conversationId: source.conversationId || null,
    status: VALID_ASSISTANT_STATES.indexOf(source.status) >= 0 ? source.status : ASSISTANT_STATES.failed,
    responseText: String(source.responseText || ""),
    streamedChunks: Array.isArray(source.streamedChunks) ? source.streamedChunks.slice() : [],
    workflowResult: clone(source.workflowResult || null),
    planning: clone(source.planning || null),
    reasoningTrace: Array.isArray(source.reasoningTrace) ? source.reasoningTrace.slice() : [],
    safety: clone(source.safety || {}),
    errors: Array.isArray(source.errors) ? source.errors.slice() : [],
    startedAt: typeof source.startedAt === "number" ? source.startedAt : null,
    completedAt: typeof source.completedAt === "number" ? source.completedAt : Date.now(),
  };
}

module.exports = {
  ASSISTANT_STATES: ASSISTANT_STATES,
  VALID_ASSISTANT_STATES: VALID_ASSISTANT_STATES,
  createExecutionRequest: createExecutionRequest,
  createReasoningStep: createReasoningStep,
  createAssistantResult: createAssistantResult,
  cloneAssistantValue: clone,
};
