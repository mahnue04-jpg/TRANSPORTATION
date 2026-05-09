"use strict";

const { createWorkflow, TASK_STATUS } = require("./planningSchemas");
const { createTaskGraph, detectCycles, computeDepth } = require("./taskGraph");
const { selectToolForTask } = require("./toolSelector");

function validateRecursion(workflow, limits) {
  var errors = [];
  if (workflow.tasks.length > limits.recursionLimit) {
    errors.push({ code: "recursion-limit", message: "Task count exceeded recursion limit" });
  }
  return errors;
}

function validateDepth(graph, limits) {
  var depth = computeDepth(graph);
  var errors = [];
  if (depth > limits.executionDepthLimit) {
    errors.push({ code: "execution-depth-limit", message: "Execution depth " + depth + " exceeds limit " + limits.executionDepthLimit });
  }
  return { errors: errors, depth: depth };
}

function validateTimeoutBudget(workflow, limits) {
  var totalBudget = 0;
  for (var i = 0; i < workflow.tasks.length; i++) {
    totalBudget += workflow.tasks[i].timeoutMs;
  }
  if (totalBudget > limits.timeoutBudgetMs) {
    return [{ code: "timeout-budget", message: "Task timeout budget " + totalBudget + "ms exceeds workflow limit " + limits.timeoutBudgetMs + "ms" }];
  }
  return [];
}

function validateToolPermissions(workflow, config) {
  var issues = [];
  var permissions = Array.isArray(config.permissions) ? config.permissions : [];
  for (var i = 0; i < workflow.tasks.length; i++) {
    var task = workflow.tasks[i];
    var selected = selectToolForTask(task, {
      runtime: config.runtime,
      permissions: permissions,
    });

    if (!selected.valid) {
      issues.push({
        code: "tool-selection",
        message: "Task " + task.id + " has invalid tool selection: " + selected.reason,
        taskId: task.id,
      });
    }
  }
  return issues;
}

function validateStatuses(workflow) {
  var issues = [];
  for (var i = 0; i < workflow.tasks.length; i++) {
    var status = workflow.tasks[i].status;
    if (Object.keys(TASK_STATUS).indexOf(status) < 0) {
      issues.push({ code: "invalid-task-status", message: "Task " + workflow.tasks[i].id + " has unsupported status: " + status });
    }
  }
  return issues;
}

function validateWorkflowPlan(workflowInput, options) {
  var config = Object.assign(
    {
      recursionLimit: 200,
      executionDepthLimit: 40,
      timeoutBudgetMs: 120000,
      permissions: [],
      runtime: null,
    },
    options || {}
  );

  var workflow = createWorkflow(workflowInput);
  var errors = [];
  var warnings = [];
  var graph = null;

  errors = errors.concat(validateRecursion(workflow, config));
  errors = errors.concat(validateStatuses(workflow));

  try {
    graph = createTaskGraph(workflow.tasks);
  } catch (error) {
    errors.push({ code: "task-graph", message: error.message });
  }

  if (graph) {
    var cycle = detectCycles(graph);
    if (cycle.hasCycle) {
      errors.push({ code: "cycle-detected", message: "Workflow contains dependency cycles", cycles: cycle.cycles });
    } else {
      var depth = validateDepth(graph, config);
      errors = errors.concat(depth.errors);

      if (depth.depth > Math.floor(config.executionDepthLimit * 0.8) && depth.depth <= config.executionDepthLimit) {
        warnings.push({ code: "depth-near-limit", message: "Workflow depth " + depth.depth + " is near execution depth limit" });
      }
    }
  }

  errors = errors.concat(validateTimeoutBudget(workflow, config));
  errors = errors.concat(validateToolPermissions(workflow, config));

  return {
    valid: errors.length === 0,
    errors: errors,
    warnings: warnings,
    metrics: {
      taskCount: workflow.tasks.length,
      timeoutBudgetMs: workflow.timeoutBudgetMs,
    },
  };
}

module.exports = {
  validateWorkflowPlan: validateWorkflowPlan,
};
