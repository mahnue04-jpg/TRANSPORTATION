"use strict";

const { createTaskPlanner, createWorkflowEngine } = require("../planning");
const goalInterpreter = require("./goalInterpreter");
const intentParser = require("./intentParser");
const { createContextManager } = require("./contextManager");
const { createSafetyGuardrails } = require("./safetyGuardrails");
const { createExecutionCoordinator } = require("./executionCoordinator");
const { createResponseSynthesizer } = require("./responseSynthesizer");
const { createConversationState } = require("./conversationState");
const { createAssistantExecutor } = require("./assistantExecutor");

function buildDefaultExecutorConfig(options) {
  var config = Object.assign({}, options || {});
  var runtime = config.runtime || null;
  var memoryManager = config.memoryManager || null;
  var orchestrator = config.orchestrator || null;
  var permissions = Array.isArray(config.permissions) ? config.permissions : [];

  var planner = config.planner || createTaskPlanner({
    runtime: runtime,
    memoryManager: memoryManager,
    orchestrator: orchestrator,
    permissions: permissions,
  });

  var workflowEngine = config.workflowEngine || createWorkflowEngine({
    runtime: runtime,
    memoryManager: memoryManager,
    orchestrator: orchestrator,
    permissions: permissions,
  });

  var safetyGuardrails = config.safetyGuardrails || createSafetyGuardrails({
    maxWorkflowDepth: typeof config.maxWorkflowDepth === "number" ? config.maxWorkflowDepth : 8,
    timeoutBudgetMs: typeof config.timeoutBudgetMs === "number" ? config.timeoutBudgetMs : 45000,
  });

  var contextManager = config.contextManager || createContextManager({
    memoryManager: memoryManager,
    maxContextTokens: typeof config.maxContextTokens === "number" ? config.maxContextTokens : 500,
  });

  var executionCoordinator = config.executionCoordinator || createExecutionCoordinator({
    planner: planner,
    workflowEngine: workflowEngine,
    safetyGuardrails: safetyGuardrails,
    runtime: runtime,
    permissions: permissions,
    orchestrator: orchestrator,
  });

  var responseSynthesizer = config.responseSynthesizer || createResponseSynthesizer({
    streamingEngine: config.streamingEngine || null,
    safetyGuardrails: safetyGuardrails,
  });

  return Object.assign({}, config, {
    goalInterpreter: config.goalInterpreter || goalInterpreter,
    intentParser: config.intentParser || intentParser,
    contextManager: contextManager,
    executionCoordinator: executionCoordinator,
    responseSynthesizer: responseSynthesizer,
    safetyGuardrails: safetyGuardrails,
  });
}

function createAssistantController(options) {
  var config = buildDefaultExecutorConfig(options || {});
  var conversations = new Map();
  var executor = config.executor || createAssistantExecutor(config);

  function getConversation(conversationId) {
    var id = String(conversationId || "default");
    if (!conversations.has(id)) {
      conversations.set(id, createConversationState(id));
    }
    return conversations.get(id);
  }

  async function run(request) {
    var input = request || {};
    var conversation = getConversation(input.conversationId || "default");
    return executor.execute(input, conversation);
  }

  function interrupt(requestId, conversationId, reason) {
    var result = executor.interrupt(requestId, reason);
    if (conversationId) {
      var conversation = getConversation(conversationId);
      conversation.interrupt(reason || "interrupted");
    }
    return result;
  }

  function snapshot(conversationId) {
    return getConversation(conversationId || "default").snapshot();
  }

  return {
    run: run,
    interrupt: interrupt,
    snapshot: snapshot,
    getConversation: getConversation,
  };
}

module.exports = {
  createAssistantController: createAssistantController,
};
