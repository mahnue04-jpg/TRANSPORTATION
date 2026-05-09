"use strict";

const { ASSISTANT_STATES, createExecutionRequest, createAssistantResult, createReasoningStep } = require("./assistantSchemas");

function createAssistantExecutor(options) {
  var config = Object.assign(
    {
      goalInterpreter: null,
      intentParser: null,
      contextManager: null,
      executionCoordinator: null,
      responseSynthesizer: null,
      safetyGuardrails: null,
      runtime: null,
      orchestrator: null,
      permissions: [],
    },
    options || {}
  );

  var inflight = new Map();

  function listRuntimeTools() {
    if (!config.runtime || typeof config.runtime.listTools !== "function") {
      return [];
    }
    return config.runtime.listTools() || [];
  }

  async function execute(requestInput, conversationState) {
    var request = createExecutionRequest(requestInput || {});
    if ((!request.permissions || request.permissions.length === 0) && Array.isArray(config.permissions) && config.permissions.length > 0) {
      request.permissions = config.permissions.slice();
    }
    var startedAt = Date.now();
    var reasoning = [];
    var errors = [];
    var streamedChunks = [];

    var signal = {
      interrupted: false,
      reason: null,
    };
    inflight.set(request.id, signal);

    function isInterrupted() {
      return signal.interrupted || (conversationState && conversationState.interrupted);
    }

    function markState(next, details) {
      if (conversationState) {
        conversationState.setState(next, details || {});
      }
      if (config.orchestrator && typeof config.orchestrator.emit === "function") {
        config.orchestrator.emit("onAgentEvent", {
          type: "assistant-state",
          requestId: request.id,
          state: next,
          details: details || {},
        });
      }
    }

    try {
      markState(ASSISTANT_STATES.interpreting, { requestId: request.id });

      var requestSafety = config.safetyGuardrails.validateRequest(request, listRuntimeTools());
      if (!requestSafety.valid) {
        errors = errors.concat(requestSafety.issues);
        markState(ASSISTANT_STATES.failed, { reason: "request-safety" });
        return createAssistantResult({
          requestId: request.id,
          conversationId: request.conversationId,
          status: ASSISTANT_STATES.failed,
          responseText: "Request blocked by assistant safety guardrails.",
          reasoningTrace: reasoning.concat(createReasoningStep("safety", "Request blocked", requestSafety)),
          safety: requestSafety,
          errors: errors,
          startedAt: startedAt,
          completedAt: Date.now(),
        });
      }

      var interpreted = config.goalInterpreter.interpretGoal(request.userGoal);
      reasoning.push(createReasoningStep("interpreting", "Goal interpreted", interpreted));
      if (!interpreted.valid) {
        markState(ASSISTANT_STATES.failed, { reason: interpreted.error || "invalid-goal" });
        errors.push({ code: interpreted.error || "invalid-goal", message: "Malformed goal" });
        return createAssistantResult({
          requestId: request.id,
          conversationId: request.conversationId,
          status: ASSISTANT_STATES.failed,
          responseText: "I could not parse your goal. Please provide a clear request.",
          reasoningTrace: reasoning,
          errors: errors,
          startedAt: startedAt,
          completedAt: Date.now(),
        });
      }

      var intent = config.intentParser.parseIntent(interpreted);
      reasoning.push(createReasoningStep("interpreting", "Intent parsed", {
        intentCount: intent.intents.length,
        conflicts: intent.conflicts,
      }));

      if (!intent.valid) {
        markState(ASSISTANT_STATES.failed, { reason: "intent-conflict" });
        errors = errors.concat(intent.conflicts);
        return createAssistantResult({
          requestId: request.id,
          conversationId: request.conversationId,
          status: ASSISTANT_STATES.failed,
          responseText: "I found conflicting tasks in your request. Please simplify the goal.",
          reasoningTrace: reasoning,
          errors: errors,
          startedAt: startedAt,
          completedAt: Date.now(),
        });
      }

      if (isInterrupted()) {
        markState(ASSISTANT_STATES.interrupted, { phase: "interpreting" });
        return createAssistantResult({
          requestId: request.id,
          conversationId: request.conversationId,
          status: ASSISTANT_STATES.interrupted,
          responseText: "Execution interrupted.",
          reasoningTrace: reasoning,
          startedAt: startedAt,
          completedAt: Date.now(),
        });
      }

      markState(ASSISTANT_STATES.planning, { intents: intent.intents.length });
      var context = await config.contextManager.buildContext({
        userGoal: request.userGoal,
        conversationState: conversationState,
      });

      reasoning.push(createReasoningStep("planning", "Context assembled", {
        tokenEstimate: context.tokenEstimate,
        overflow: context.overflow,
      }));

      if (isInterrupted()) {
        markState(ASSISTANT_STATES.interrupted, { phase: "planning" });
        return createAssistantResult({
          requestId: request.id,
          conversationId: request.conversationId,
          status: ASSISTANT_STATES.interrupted,
          responseText: "Execution interrupted.",
          reasoningTrace: reasoning,
          startedAt: startedAt,
          completedAt: Date.now(),
        });
      }

      markState(ASSISTANT_STATES.executing, {});
      var coordinated = await config.executionCoordinator.coordinate({
        request: request,
        interpretedGoal: interpreted,
        intent: intent,
        context: context,
      });

      reasoning = reasoning.concat(coordinated.reasoning || []);

      if (isInterrupted()) {
        markState(ASSISTANT_STATES.interrupted, { phase: "executing" });
        if (coordinated.planning && coordinated.planning.workflow) {
          config.executionCoordinator.config.workflowEngine.cancelWorkflow(coordinated.planning.workflow.id, "assistant-interrupted");
        }
        return createAssistantResult({
          requestId: request.id,
          conversationId: request.conversationId,
          status: ASSISTANT_STATES.interrupted,
          responseText: "Execution interrupted.",
          planning: coordinated.planning,
          workflowResult: coordinated.workflowResult,
          reasoningTrace: reasoning,
          startedAt: startedAt,
          completedAt: Date.now(),
        });
      }

      if (!coordinated.ok) {
        markState(ASSISTANT_STATES.failed, { reason: coordinated.error || "execution-failed" });
        errors.push({ code: coordinated.error || "execution-failed", message: "Coordinator returned failure" });
        if (coordinated.safety && coordinated.safety.issues) {
          errors = errors.concat(coordinated.safety.issues);
        }
        return createAssistantResult({
          requestId: request.id,
          conversationId: request.conversationId,
          status: ASSISTANT_STATES.failed,
          responseText: "Unable to complete execution safely.",
          planning: coordinated.planning,
          workflowResult: coordinated.workflowResult,
          reasoningTrace: reasoning,
          safety: coordinated.safety,
          errors: errors,
          startedAt: startedAt,
          completedAt: Date.now(),
        });
      }

      markState(ASSISTANT_STATES.responding, {});
      var response = config.responseSynthesizer.synthesize({
        request: request,
        context: context,
        execution: coordinated,
      });
      reasoning = reasoning.concat(response.reasoning || []);

      streamedChunks = config.responseSynthesizer.stream(response, {
        onChunk: function (chunk) {
          if (typeof requestInput.onStreamChunk === "function") {
            requestInput.onStreamChunk(chunk);
          }
        },
        streamingSession: requestInput.streamingSession || null,
      });

      if (conversationState) {
        conversationState.addMessage("user", request.userGoal, { requestId: request.id });
        conversationState.addMessage("assistant", response.text, { requestId: request.id, status: ASSISTANT_STATES.completed });
      }

      markState(ASSISTANT_STATES.completed, {});
      return createAssistantResult({
        requestId: request.id,
        conversationId: request.conversationId,
        status: ASSISTANT_STATES.completed,
        responseText: response.text,
        streamedChunks: streamedChunks,
        planning: coordinated.planning,
        workflowResult: coordinated.workflowResult,
        reasoningTrace: reasoning,
        safety: response.evidence,
        errors: errors,
        startedAt: startedAt,
        completedAt: Date.now(),
      });
    } catch (error) {
      markState(ASSISTANT_STATES.failed, { reason: error.message });
      errors.push({ code: "executor-error", message: error.message });
      return createAssistantResult({
        requestId: request.id,
        conversationId: request.conversationId,
        status: ASSISTANT_STATES.failed,
        responseText: "Assistant execution failed due to an internal error.",
        reasoningTrace: reasoning,
        errors: errors,
        startedAt: startedAt,
        completedAt: Date.now(),
      });
    } finally {
      inflight.delete(request.id);
    }
  }

  function interrupt(requestId, reason) {
    var inflightSignal = inflight.get(requestId);
    if (!inflightSignal) {
      return { interrupted: false, reason: "request-not-found" };
    }
    inflightSignal.interrupted = true;
    inflightSignal.reason = reason ? String(reason) : "interrupted";
    return { interrupted: true, requestId: requestId, reason: inflightSignal.reason };
  }

  return {
    execute: execute,
    interrupt: interrupt,
  };
}

module.exports = {
  createAssistantExecutor: createAssistantExecutor,
};
