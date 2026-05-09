"use strict";

const ASSISTANT_UI_STATES = {
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

const TERMINAL_STATES = {
  interrupted: true,
  failed: true,
  completed: true,
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
  return String(prefix || "conversation") + "-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
}

function createConversationMessage(input) {
  var source = input || {};
  return {
    id: String(source.id || uid("msg")),
    at: typeof source.at === "number" ? source.at : Date.now(),
    role: String(source.role || "assistant"),
    text: String(source.text || ""),
    streaming: !!source.streaming,
    metadata: clone(source.metadata || {}),
  };
}

function createConversationSession(input) {
  var source = input || {};
  var messages = Array.isArray(source.messages)
    ? source.messages.map(createConversationMessage)
    : [];

  return {
    id: String(source.id || uid("session")),
    title: String(source.title || "New Conversation"),
    createdAt: typeof source.createdAt === "number" ? source.createdAt : Date.now(),
    updatedAt: typeof source.updatedAt === "number" ? source.updatedAt : Date.now(),
    assistantState: ASSISTANT_UI_STATES.idle,
    messages: messages,
    workflowHistory: Array.isArray(source.workflowHistory) ? clone(source.workflowHistory) : [],
    toolActivity: Array.isArray(source.toolActivity) ? clone(source.toolActivity) : [],
    executionFeed: Array.isArray(source.executionFeed) ? clone(source.executionFeed) : [],
    memoryContext: clone(source.memoryContext || { summary: "", indicators: [] }),
  };
}

function validateAssistantState(state) {
  var value = String(state || "");
  if (ASSISTANT_UI_STATES[value]) {
    return value;
  }
  return ASSISTANT_UI_STATES.failed;
}

module.exports = {
  ASSISTANT_UI_STATES: ASSISTANT_UI_STATES,
  TERMINAL_STATES: TERMINAL_STATES,
  cloneConversationValue: clone,
  createConversationMessage: createConversationMessage,
  createConversationSession: createConversationSession,
  validateAssistantState: validateAssistantState,
  createConversationUid: uid,
};
