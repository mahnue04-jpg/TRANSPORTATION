"use strict";

function createSafetyGuardrails(options) {
  var config = Object.assign(
    {
      recursionLimit: 3,
      maxWorkflowDepth: 8,
      timeoutBudgetMs: 45000,
      forbiddenPatterns: [
        /self-modif/i,
        /rewrite yourself/i,
        /autonomous recursive/i,
        /infinite loop/i,
      ],
      requiredEvidenceForClaims: true,
    },
    options || {}
  );

  function validateRequest(request, runtimeTools) {
    var issues = [];

    if (!request.userGoal || !String(request.userGoal).trim()) {
      issues.push({ code: "empty-goal", message: "User goal is empty" });
    }

    for (var i = 0; i < config.forbiddenPatterns.length; i++) {
      if (config.forbiddenPatterns[i].test(request.userGoal || "")) {
        issues.push({ code: "forbidden-goal", message: "Goal requests prohibited autonomous behavior" });
        break;
      }
    }

    if (request.maxDepth > config.maxWorkflowDepth) {
      issues.push({ code: "max-depth", message: "Requested depth exceeds configured maximum" });
    }

    if (request.timeoutBudgetMs > config.timeoutBudgetMs) {
      issues.push({ code: "timeout-budget", message: "Requested timeout exceeds configured budget" });
    }

    var tools = Array.isArray(runtimeTools) ? runtimeTools : [];
    if (tools.length === 0) {
      issues.push({ code: "runtime-tools", message: "No runtime tools available" });
    }

    return { valid: issues.length === 0, issues: issues };
  }

  function validateWorkflowSafety(planResult) {
    var issues = [];
    if (planResult && planResult.validation && !planResult.validation.valid) {
      issues.push({ code: "plan-invalid", message: "Planning validation failed", errors: planResult.validation.errors || [] });
    }

    if (planResult && planResult.workflow && Array.isArray(planResult.workflow.tasks) && planResult.workflow.tasks.length > config.recursionLimit * 20) {
      issues.push({ code: "recursion-risk", message: "Workflow task count indicates recursion risk" });
    }

    return { valid: issues.length === 0, issues: issues };
  }

  function validateToolPermissions(workflow, permissions, runtimeTools) {
    var issues = [];
    var granted = Array.isArray(permissions) ? permissions : [];
    var tools = Array.isArray(runtimeTools) ? runtimeTools : [];
    var toolByName = Object.create(null);

    for (var i = 0; i < tools.length; i++) {
      toolByName[tools[i].name] = tools[i];
    }

    var tasks = workflow && Array.isArray(workflow.tasks) ? workflow.tasks : [];
    for (var j = 0; j < tasks.length; j++) {
      var task = tasks[j];
      if (!task.assignedTool) {
        continue;
      }
      var tool = toolByName[task.assignedTool];
      if (!tool) {
        issues.push({ code: "invalid-tool", message: "Task references unknown tool: " + task.assignedTool, taskId: task.id });
        continue;
      }
      var required = Array.isArray(tool.permissions) ? tool.permissions : [];
      for (var k = 0; k < required.length; k++) {
        if (granted.indexOf(required[k]) < 0) {
          issues.push({ code: "permission-denied", message: "Missing permission '" + required[k] + "' for tool " + task.assignedTool, taskId: task.id });
        }
      }
    }

    return { valid: issues.length === 0, issues: issues };
  }

  function validateEvidence(responseDraft, executionSummary) {
    if (!config.requiredEvidenceForClaims) {
      return { valid: true, issues: [] };
    }
    var issues = [];
    var claims = String(responseDraft || "").toLowerCase();
    var completedTasks = executionSummary && executionSummary.summary ? executionSummary.summary.completedTasks : 0;

    if (claims.indexOf("completed") >= 0 && completedTasks === 0) {
      issues.push({ code: "unsupported-claim", message: "Response claims completion but no tasks completed" });
    }

    return { valid: issues.length === 0, issues: issues };
  }

  return {
    config: config,
    validateRequest: validateRequest,
    validateWorkflowSafety: validateWorkflowSafety,
    validateToolPermissions: validateToolPermissions,
    validateEvidence: validateEvidence,
  };
}

module.exports = {
  createSafetyGuardrails: createSafetyGuardrails,
};
