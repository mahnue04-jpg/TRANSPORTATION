"use strict";

const { ASSISTANT_UI_STATES } = require("./ConversationSchemas");

var STATE_STYLE = {
  idle: { label: "Idle", tone: "neutral" },
  interpreting: { label: "Interpreting", tone: "info" },
  planning: { label: "Planning", tone: "info" },
  executing: { label: "Executing", tone: "active" },
  responding: { label: "Responding", tone: "active" },
  waiting: { label: "Waiting", tone: "warning" },
  interrupted: { label: "Interrupted", tone: "warning" },
  failed: { label: "Failed", tone: "error" },
  completed: { label: "Completed", tone: "success" },
};

function buildAssistantStateModel(state, progress) {
  var value = ASSISTANT_UI_STATES[state] ? state : ASSISTANT_UI_STATES.failed;
  var style = STATE_STYLE[value] || STATE_STYLE.failed;
  return {
    state: value,
    label: style.label,
    tone: style.tone,
    progressPercent: typeof progress === "number" ? Math.max(0, Math.min(100, progress)) : null,
  };
}

function AssistantStateIndicator(props) {
  return {
    type: "AssistantStateIndicator",
    model: buildAssistantStateModel(props && props.state, props && props.progressPercent),
  };
}

module.exports = {
  AssistantStateIndicator: AssistantStateIndicator,
  buildAssistantStateModel: buildAssistantStateModel,
};
