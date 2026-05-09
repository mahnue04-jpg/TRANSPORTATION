"use strict";

const { createWorkflow, TASK_STATUS, WORKFLOW_STATUS } = require("./planningSchemas");
const { createTaskGraph } = require("./taskGraph");
const { resolveDependencies } = require("./dependencyResolver");
const { createWorkflowState } = require("./workflowState");
const { createExecutionTracker } = require("./executionTracker");
const { createRecoveryPlanner } = require("./recoveryPlanner");
const { selectToolForTask } = require("./toolSelector");
const { validateWorkflowPlan } = require("./planningValidator");

function wait(ms) {
  if (!ms) {
    return Promise.resolve();
  }
  return new Promise(function (resolve) {
    setTimeout(resolve, ms);
  });
}

function conditionPasses(task, state) {
  if (!task.condition) {
    return true;
  }

  if (typeof task.condition === "function") {
    return !!task.condition(state.snapshot());
  }

  if (task.condition.type === "output_exists") {
    var depTask = state.getTask(task.condition.taskId);
    if (!depTask || !depTask.outputs) {
      return false;
    }
    if (!task.condition.field) {
      return true;
    }
    return depTask.outputs[task.condition.field] !== undefined;
  }

  if (task.condition.type === "equals") {
    var target = state.getTask(task.condition.taskId);
    if (!target || !target.outputs) {
      return false;
    }
    return target.outputs[task.condition.field] === task.condition.value;
  }

  return true;
}

function getRuntime(runtimeOverride) {
  if (runtimeOverride) {
    return runtimeOverride;
  }
  if (typeof global !== "undefined" && global.AmiCorToolRuntime) {
    return global.AmiCorToolRuntime;
  }
  if (typeof window !== "undefined" && window.AmiCorToolRuntime) {
    return window.AmiCorToolRuntime;
  }
  return null;
}

function createWorkflowEngine(options) {
  var config = Object.assign(
    {
      runtime: null,
      planner: null,
      memoryManager: null,
      orchestrator: null,
      permissions: [],
      recursionLimit: 200,
      executionDepthLimit: 40,
      timeoutBudgetMs: 120000,
      maxConcurrentTasks: 1,
    },
    options || {}
  );

  var recoveryPlanner = config.recoveryPlanner || createRecoveryPlanner({});
  var activeWorkflows = new Map();

  function emit(eventName, payload) {
    if (config.orchestrator && typeof config.orchestrator.emit === "function") {
      config.orchestrator.emit(eventName, payload);
    }
  }

  async function executeSingleTask(context, graph, taskId, budget) {
    var state = context.state;
    var tracker = context.tracker;
    var runtime = context.runtime;

    var task = state.getTask(taskId);
    if (!task) {
      return;
    }

    if (context.cancelled) {
      state.setTaskStatus(taskId, TASK_STATUS.cancelled);
      tracker.recordTaskCancelled(taskId, "workflow-cancelled");
      return;
    }

    if (!conditionPasses(task, state)) {
      state.setTaskStatus(taskId, TASK_STATUS.cancelled, {
        outputs: { skipped: true, reason: "condition-false" },
      });
      tracker.recordTaskCancelled(taskId, "condition-false");
      return;
    }

    var selection = selectToolForTask(task, {
      runtime: runtime,
      permissions: config.permissions,
    });

    if (!selection.valid || !selection.selectedTool) {
      state.setTaskStatus(taskId, TASK_STATUS.failed, {
        outputs: { error: "tool-selection-failed", reason: selection.reason },
      });
      tracker.recordTaskFailure(taskId, { message: selection.reason });
      return;
    }

    task.assignedTool = selection.selectedTool;
    state.setTaskStatus(taskId, TASK_STATUS.running);
    tracker.recordTaskStart(taskId, selection.selectedTool);

    var timeoutRemaining = Math.max(1, budget.remainingMs());
    var timeoutMs = Math.min(task.timeoutMs, timeoutRemaining);
    var start = Date.now();

    try {
      var execOptions = {
        timeoutMs: timeoutMs,
        retryMax: 0,
        permissions: config.permissions,
      };

      if (context.abortController && context.abortController.signal) {
        execOptions.signal = context.abortController.signal;
      }

      var output = await runtime.execute(task.assignedTool, task.input || {}, execOptions);
      state.setTaskStatus(taskId, TASK_STATUS.completed, { outputs: output });
      tracker.recordTaskComplete(taskId, output);
      budget.consume(Date.now() - start);
      if (config.memoryManager && typeof config.memoryManager.addWorkflowMemory === "function") {
        await config.memoryManager.addWorkflowMemory("task " + taskId + " completed", {
          workflowId: context.workflow.id,
          taskId: taskId,
          tool: task.assignedTool,
        });
      }
    } catch (error) {
      budget.consume(Date.now() - start);
      var retry = recoveryPlanner.planRetry(task, {
        message: error && error.message ? error.message : String(error),
      });

      if (retry.shouldRetry) {
        task.retries.attempted = retry.nextAttempt;
        state.setTaskStatus(taskId, TASK_STATUS.ready);
        tracker.recordTaskRetry(taskId, retry.reason, retry.delayMs);
        await wait(retry.delayMs);
        return;
      }

      var fallback = recoveryPlanner.planFallback(task, state, graph);
      if (fallback.useFallback && !fallback.alreadyCompleted) {
        var fallbackTask = state.getTask(fallback.fallbackTaskId);
        if (fallbackTask.status === TASK_STATUS.pending || fallbackTask.status === TASK_STATUS.ready || fallbackTask.status === TASK_STATUS.blocked) {
          state.setTaskStatus(fallbackTask.id, TASK_STATUS.ready);
          await executeSingleTask(context, graph, fallbackTask.id, budget);
        }
      }

      if (fallback.useFallback) {
        var finalFallbackTask = state.getTask(fallback.fallbackTaskId);
        if (finalFallbackTask && finalFallbackTask.status === TASK_STATUS.completed) {
          state.setTaskStatus(taskId, TASK_STATUS.completed, {
            outputs: { fallbackUsed: true, fallbackTaskId: fallback.fallbackTaskId, originalError: error.message || String(error) },
          });
          tracker.recordTaskComplete(taskId, { fallback: fallback.fallbackTaskId });
          return;
        }
      }

      state.setTaskStatus(taskId, TASK_STATUS.failed, {
        outputs: { error: error.message || String(error) },
      });
      tracker.recordTaskFailure(taskId, { message: error.message || String(error) });

      var continuation = recoveryPlanner.planPartialContinuation(state, graph, taskId);
      if (!continuation.continuable) {
        for (var i = 0; i < continuation.blockedTasks.length; i++) {
          var blockedTask = state.getTask(continuation.blockedTasks[i]);
          if (blockedTask && blockedTask.status !== TASK_STATUS.completed && blockedTask.status !== TASK_STATUS.failed) {
            state.setTaskStatus(blockedTask.id, TASK_STATUS.blocked);
          }
        }
      }
    }
  }

  async function executeWorkflow(workflowInput, execOptions) {
    var executeConfig = Object.assign({}, execOptions || {});

    var workflow = createWorkflow(workflowInput || {});
    var validation = validateWorkflowPlan(workflow, {
      recursionLimit: config.recursionLimit,
      executionDepthLimit: config.executionDepthLimit,
      timeoutBudgetMs: executeConfig.timeoutBudgetMs || workflow.timeoutBudgetMs || config.timeoutBudgetMs,
      runtime: config.runtime,
      permissions: config.permissions,
    });

    if (!validation.valid) {
      return {
        workflowId: workflow.id,
        status: WORKFLOW_STATUS.failed,
        validation: validation,
        error: "planning-validation-failed",
      };
    }

    var graph = createTaskGraph(workflow.tasks);
    var state = createWorkflowState(workflow);
    var tracker = createExecutionTracker(workflow.id);
    var runtime = getRuntime(config.runtime);

    if (!runtime || typeof runtime.execute !== "function") {
      return {
        workflowId: workflow.id,
        status: WORKFLOW_STATUS.failed,
        validation: validation,
        error: "runtime-unavailable",
      };
    }

    var timeoutBudgetMs = executeConfig.timeoutBudgetMs || workflow.timeoutBudgetMs || config.timeoutBudgetMs;
    var budget = {
      consumed: 0,
      consume: function (durationMs) {
        this.consumed += Math.max(0, durationMs || 0);
      },
      remainingMs: function () {
        return Math.max(0, timeoutBudgetMs - this.consumed);
      },
      exhausted: function () {
        return this.remainingMs() <= 0;
      },
    };

    var abortController = typeof AbortController !== "undefined" ? new AbortController() : null;

    var context = {
      workflow: workflow,
      state: state,
      tracker: tracker,
      runtime: runtime,
      graph: graph,
      cancelled: false,
      abortController: abortController,
    };

    activeWorkflows.set(workflow.id, context);

    state.setWorkflowStatus(WORKFLOW_STATUS.running);
    tracker.recordWorkflowStart({ goal: workflow.goal, taskCount: workflow.tasks.length });
    emit("onAgentEvent", { type: "workflow-start", workflowId: workflow.id });

    try {
      while (true) {
        if (context.cancelled) {
          break;
        }

        if (budget.exhausted()) {
          state.setWorkflowStatus(WORKFLOW_STATUS.failed);
          break;
        }

        var resolved = resolveDependencies(graph, state);

        for (var i = 0; i < resolved.blocked.length; i++) {
          var blocked = resolved.blocked[i].task;
          if (blocked.status === TASK_STATUS.pending) {
            state.setTaskStatus(blocked.id, TASK_STATUS.blocked);
          }
        }

        var readyTasks = resolved.ready;
        if (readyTasks.length === 0) {
          var counts = state.counts();
          if (counts.running > 0) {
            continue;
          }
          if (counts.pending === 0 && counts.ready === 0 && counts.blocked === 0) {
            break;
          }
          if (counts.failed > 0 && counts.completed === 0) {
            break;
          }

          var unblockable = false;
          if (counts.blocked > 0 && counts.pending === 0 && counts.ready === 0) {
            unblockable = true;
          }

          if (unblockable) {
            break;
          }

          // Re-mark blocked tasks as pending to re-evaluate dependency states.
          var tasks = state.listTasks();
          for (var r = 0; r < tasks.length; r++) {
            if (tasks[r].status === TASK_STATUS.blocked) {
              state.setTaskStatus(tasks[r].id, TASK_STATUS.pending);
            }
          }
          continue;
        }

        var batchSize = Math.max(1, config.maxConcurrentTasks);
        for (var b = 0; b < readyTasks.length && b < batchSize; b++) {
          state.setTaskStatus(readyTasks[b].id, TASK_STATUS.ready);
        }

        for (var e = 0; e < readyTasks.length && e < batchSize; e++) {
          var readyTask = state.getTask(readyTasks[e].id);
          if (readyTask && (readyTask.status === TASK_STATUS.ready || readyTask.status === TASK_STATUS.pending || readyTask.status === TASK_STATUS.blocked)) {
            await executeSingleTask(context, graph, readyTask.id, budget);
          }
        }
      }

      var finalCounts = state.counts();
      if (context.cancelled) {
        state.setWorkflowStatus(WORKFLOW_STATUS.cancelled);
      } else if (finalCounts.failed > 0 && finalCounts.completed === 0) {
        state.setWorkflowStatus(WORKFLOW_STATUS.failed);
      } else if (finalCounts.pending > 0 || finalCounts.ready > 0 || finalCounts.running > 0 || finalCounts.blocked > 0) {
        state.setWorkflowStatus(finalCounts.completed > 0 ? WORKFLOW_STATUS.completed : WORKFLOW_STATUS.blocked);
      } else {
        state.setWorkflowStatus(finalCounts.failed > 0 ? WORKFLOW_STATUS.failed : WORKFLOW_STATUS.completed);
      }

      tracker.recordWorkflowEnd(state.status, { counts: finalCounts, consumedBudgetMs: budget.consumed });
      emit("onAgentEvent", { type: "workflow-end", workflowId: workflow.id, status: state.status });

      return {
        workflowId: workflow.id,
        status: state.status,
        snapshot: state.snapshot(),
        events: tracker.getEvents(),
        summary: tracker.summary(),
        validation: validation,
        consumedBudgetMs: budget.consumed,
      };
    } finally {
      activeWorkflows.delete(workflow.id);
    }
  }

  function cancelWorkflow(workflowId, reason) {
    var context = activeWorkflows.get(workflowId);
    if (!context) {
      return { cancelled: false, reason: "workflow-not-active" };
    }

    context.cancelled = true;
    if (context.abortController) {
      context.abortController.abort();
    }

    var graph = context.graph;
    var state = context.state;
    var tracker = context.tracker;

    var tasks = state.listTasks();
    for (var i = 0; i < tasks.length; i++) {
      if (tasks[i].status === TASK_STATUS.running || tasks[i].status === TASK_STATUS.pending || tasks[i].status === TASK_STATUS.ready || tasks[i].status === TASK_STATUS.blocked) {
        state.setTaskStatus(tasks[i].id, TASK_STATUS.cancelled);
        tracker.recordTaskCancelled(tasks[i].id, reason || "cancelled");

        var dependents = graph.getDependents(tasks[i].id);
        for (var j = 0; j < dependents.length; j++) {
          var depTask = state.getTask(dependents[j]);
          if (depTask && depTask.status !== TASK_STATUS.completed && depTask.status !== TASK_STATUS.failed) {
            state.setTaskStatus(depTask.id, TASK_STATUS.cancelled);
            tracker.recordTaskCancelled(depTask.id, "cancel-propagation");
          }
        }
      }
    }

    state.setWorkflowStatus(WORKFLOW_STATUS.cancelled);
    return { cancelled: true, workflowId: workflowId, reason: reason || "cancelled" };
  }

  function recoverWorkflow(corruptSnapshot, workflowInput) {
    var workflow = createWorkflow(workflowInput || {});
    var state = createWorkflowState(workflow);
    return state.recover(corruptSnapshot || {});
  }

  return {
    config: config,
    executeWorkflow: executeWorkflow,
    cancelWorkflow: cancelWorkflow,
    recoverWorkflow: recoverWorkflow,
  };
}

module.exports = {
  createWorkflowEngine: createWorkflowEngine,
};
