"use strict";

const { createReasoningStep } = require("./assistantSchemas");

function createExecutionCoordinator(options) {
  var config = Object.assign(
    {
      planner: null,
      workflowEngine: null,
      safetyGuardrails: null,
      runtime: null,
      permissions: [],
      orchestrator: null,
    },
    options || {}
  );

  async function coordinate(input) {
    var source = input || {};
    var request = source.request;
    var intent = source.intent;
    var reasoning = [];

    if (!config.planner || !config.workflowEngine) {
      return {
        ok: false,
        error: "missing-planning-components",
        reasoning: [createReasoningStep("error", "Planner or workflow engine missing")],
      };
    }

    reasoning.push(createReasoningStep("planning", "Creating structured workflow plan", {
      intentCount: intent.intents.length,
    }));

    var tasks = intent.intents.map(function (item, index) {
      return {
        id: "task-" + (index + 1),
        type: item.taskType,
        dependencies: index === 0 ? [] : ["task-" + index],
        priority: item.priority,
        context: { clause: item.clause, intent: item.type },
      };
    });

    var planning = await config.planner.plan({
      workflowId: request.id + "-workflow",
      goal: request.userGoal,
      tasks: tasks,
      context: { executionRequestId: request.id, conversationId: request.conversationId },
      timeoutBudgetMs: request.timeoutBudgetMs,
      maxDepth: request.maxDepth,
    });

    var safetyWorkflow = config.safetyGuardrails.validateWorkflowSafety(planning);
    if (!safetyWorkflow.valid) {
      return {
        ok: false,
        error: "unsafe-workflow",
        planning: planning,
        safety: safetyWorkflow,
        reasoning: reasoning.concat(createReasoningStep("safety", "Workflow blocked by safety guardrails", safetyWorkflow)),
      };
    }

    var runtimeTools = config.runtime && typeof config.runtime.listTools === "function" ? config.runtime.listTools() : [];
    var permissionCheck = config.safetyGuardrails.validateToolPermissions(planning.workflow, request.permissions, runtimeTools);
    if (!permissionCheck.valid) {
      return {
        ok: false,
        error: "tool-permission-invalid",
        planning: planning,
        safety: permissionCheck,
        reasoning: reasoning.concat(createReasoningStep("safety", "Tool permissions validation failed", permissionCheck)),
      };
    }

    reasoning.push(createReasoningStep("execution", "Executing workflow", { workflowId: planning.workflow.id }));

    var workflowResult = await config.workflowEngine.executeWorkflow(planning.workflow, {
      timeoutBudgetMs: request.timeoutBudgetMs,
    });

    return {
      ok: workflowResult && (workflowResult.status === "completed" || workflowResult.status === "failed" || workflowResult.status === "cancelled" || workflowResult.status === "blocked"),
      planning: planning,
      workflowResult: workflowResult,
      safety: {
        workflow: safetyWorkflow,
        permissions: permissionCheck,
      },
      reasoning: reasoning.concat(createReasoningStep("execution", "Workflow execution completed", {
        status: workflowResult ? workflowResult.status : "unknown",
      })),
    };
  }

  return {
    config: config,
    coordinate: coordinate,
  };
}

module.exports = {
  createExecutionCoordinator: createExecutionCoordinator,
};
