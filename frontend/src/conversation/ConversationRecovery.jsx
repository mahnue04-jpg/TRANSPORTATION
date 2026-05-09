"use strict";

function buildRecoveryModel(session, lastResult) {
  var currentSession = session || {};
  var result = lastResult || {};
  var state = currentSession.assistantState || "idle";

  var suggestions = [];
  if (state === "failed") {
    suggestions.push({ action: "retry", label: "Retry workflow" });
    suggestions.push({ action: "continue", label: "Continue from successful steps" });
  }
  if (state === "interrupted") {
    suggestions.push({ action: "resume", label: "Resume interrupted execution" });
  }
  if (result && result.status === "failed" && result.workflowResult && result.workflowResult.snapshot) {
    suggestions.push({ action: "recover", label: "Recover from partial workflow" });
  }

  return {
    state: state,
    hasFailure: state === "failed" || state === "interrupted",
    suggestions: suggestions,
    workflowStatus: result.workflowResult ? result.workflowResult.status : null,
  };
}

function ConversationRecovery(props) {
  return {
    type: "ConversationRecovery",
    model: buildRecoveryModel(props && props.session, props && props.lastResult),
  };
}

module.exports = {
  ConversationRecovery: ConversationRecovery,
  buildRecoveryModel: buildRecoveryModel,
};
