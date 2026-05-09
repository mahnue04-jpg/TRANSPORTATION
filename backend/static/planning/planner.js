"use strict";

const { createTask, createWorkflow, createWorkflowVisualization } = require("./planningSchemas");
const { selectToolForTask } = require("./toolSelector");
const { validateWorkflowPlan } = require("./planningValidator");

function createTaskPlanner(options) {
  var config = Object.assign(
    {
      runtime: null,
      memoryManager: null,
      orchestrator: null,
      permissions: [],
      recursionLimit: 200,
      executionDepthLimit: 40,
      timeoutBudgetMs: 120000,
    },
    options || {}
  );

  async function buildContext(input) {
    var planningContext = {
      query: input.goal || "",
      memorySummary: null,
      retrievedMemories: [],
      userContext: input.context || {},
    };

    if (!config.memoryManager) {
      return planningContext;
    }

    try {
      var retrieval = await config.memoryManager.retrieve(input.goal || "", { limit: 10 });
      planningContext.retrievedMemories = retrieval.items || [];

      var assembled = await config.memoryManager.assembleContext({ query: input.goal || "", maxTokens: 300 });
      planningContext.memorySummary = assembled.context || "";
    } catch (error) {
      planningContext.memorySummary = "memory-unavailable:" + error.message;
    }

    return planningContext;
  }

  function normalizeTasks(inputTasks, planningContext) {
    var tasksArray = Array.isArray(inputTasks) ? inputTasks : [];
    var allObjects = tasksArray.length > 0 && tasksArray.every(function (item) {
      return item && typeof item === "object" && !Array.isArray(item);
    });

    if (allObjects) {
      return tasksArray.map(function (taskInput) {
        var task = createTask(taskInput);
        task.context = Object.assign({}, planningContext.userContext || {}, task.context || {}, {
          memorySummary: planningContext.memorySummary,
        });

        var selected = selectToolForTask(task, {
          runtime: config.runtime,
          permissions: config.permissions,
        });
        if (selected.valid) {
          task.assignedTool = selected.selectedTool;
        }

        return task;
      });
    }

    var steps = tasksArray;
    var tasks = [];

    for (var i = 0; i < steps.length; i++) {
      var id = "task-" + (i + 1);
      var task = createTask({
        id: id,
        type: "generic",
        dependencies: i === 0 ? [] : ["task-" + i],
        priority: 50,
        context: {
          step: String(steps[i]),
          memorySummary: planningContext.memorySummary,
        },
      });

      var selected = selectToolForTask(task, {
        runtime: config.runtime,
        permissions: config.permissions,
      });
      if (selected.valid) {
        task.assignedTool = selected.selectedTool;
      }

      tasks.push(task);
    }

    return tasks;
  }

  function emitPlanningEvent(payload) {
    var orchestrator = config.orchestrator;
    if (!orchestrator) {
      return;
    }

    if (typeof orchestrator.emit === "function") {
      orchestrator.emit("onAgentEvent", payload);
    } else if (typeof orchestrator._emit === "function") {
      orchestrator._emit("onAgentEvent", payload);
    }
  }

  async function plan(input) {
    var request = input || {};
    var planningContext = await buildContext(request);

    var taskSource = Array.isArray(request.tasks) ? request.tasks : request.steps;
    var tasks = normalizeTasks(taskSource || [], planningContext);
    var workflow = createWorkflow({
      id: request.workflowId,
      goal: request.goal || "",
      tasks: tasks,
      context: Object.assign({}, request.context || {}, {
        planningContext: planningContext,
      }),
      timeoutBudgetMs: typeof request.timeoutBudgetMs === "number" ? request.timeoutBudgetMs : config.timeoutBudgetMs,
      maxDepth: typeof request.maxDepth === "number" ? request.maxDepth : config.executionDepthLimit,
      metadata: request.metadata || {},
    });

    var validation = validateWorkflowPlan(workflow, {
      recursionLimit: config.recursionLimit,
      executionDepthLimit: config.executionDepthLimit,
      timeoutBudgetMs: workflow.timeoutBudgetMs,
      runtime: config.runtime,
      permissions: config.permissions,
    });

    var visualization = createWorkflowVisualization(workflow);

    emitPlanningEvent({
      type: "planning-created",
      workflowId: workflow.id,
      valid: validation.valid,
      taskCount: workflow.tasks.length,
    });

    return {
      workflow: workflow,
      validation: validation,
      visualization: visualization,
      planningContext: planningContext,
    };
  }

  return {
    config: config,
    plan: plan,
  };
}

module.exports = {
  createTaskPlanner: createTaskPlanner,
};
