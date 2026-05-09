"use strict";

const { createWorkflow, createTask, TASK_STATUS, WORKFLOW_STATUS, clonePlanningValue } = require("./planningSchemas");

function createWorkflowState(workflowInput) {
  var workflow = createWorkflow(workflowInput || {});
  var tasksById = Object.create(null);
  var taskIds = [];

  for (var i = 0; i < workflow.tasks.length; i++) {
    var task = createTask(workflow.tasks[i]);
    tasksById[task.id] = task;
    taskIds.push(task.id);
  }

  var status = workflow.status || WORKFLOW_STATUS.pending;
  var timeline = [];

  function appendTimeline(event, details) {
    timeline.push({
      at: Date.now(),
      event: event,
      details: clonePlanningValue(details || {}),
    });
  }

  function setWorkflowStatus(nextStatus) {
    if (status === nextStatus) {
      return;
    }
    status = nextStatus;
    appendTimeline("workflow-status", { status: nextStatus });
  }

  function setTaskStatus(taskId, nextStatus, patch) {
    var task = tasksById[taskId];
    if (!task) {
      throw new Error("Unknown task id: " + taskId);
    }
    task.status = nextStatus;
    if (patch && typeof patch === "object") {
      var keys = Object.keys(patch);
      for (var i = 0; i < keys.length; i++) {
        task[keys[i]] = clonePlanningValue(patch[keys[i]]);
      }
    }
    appendTimeline("task-status", { taskId: taskId, status: nextStatus, patch: patch || null });
  }

  function getTask(taskId) {
    return tasksById[taskId] || null;
  }

  function listTasks() {
    var out = [];
    for (var i = 0; i < taskIds.length; i++) {
      out.push(tasksById[taskIds[i]]);
    }
    return out;
  }

  function counts() {
    var out = {
      pending: 0,
      ready: 0,
      running: 0,
      blocked: 0,
      failed: 0,
      completed: 0,
      cancelled: 0,
    };

    var tasks = listTasks();
    for (var i = 0; i < tasks.length; i++) {
      if (out[tasks[i].status] !== undefined) {
        out[tasks[i].status] += 1;
      }
    }

    return out;
  }

  function snapshot() {
    return {
      workflow: {
        id: workflow.id,
        goal: workflow.goal,
        status: status,
        createdAt: workflow.createdAt,
        startedAt: workflow.startedAt,
        completedAt: workflow.completedAt,
        context: clonePlanningValue(workflow.context),
        maxDepth: workflow.maxDepth,
        timeoutBudgetMs: workflow.timeoutBudgetMs,
        metadata: clonePlanningValue(workflow.metadata),
      },
      tasks: listTasks().map(function (task) {
        return clonePlanningValue(task);
      }),
      timeline: clonePlanningValue(timeline),
      counts: counts(),
    };
  }

  function recover(corruptSnapshot) {
    var recoveredTasks = Object.create(null);
    var inputTasks = Array.isArray(corruptSnapshot && corruptSnapshot.tasks) ? corruptSnapshot.tasks : [];

    for (var i = 0; i < taskIds.length; i++) {
      var taskId = taskIds[i];
      var found = null;
      for (var j = 0; j < inputTasks.length; j++) {
        if (inputTasks[j] && inputTasks[j].id === taskId) {
          found = inputTasks[j];
          break;
        }
      }

      if (!found) {
        recoveredTasks[taskId] = createTask(tasksById[taskId]);
        continue;
      }

      var merged = createTask(Object.assign({}, tasksById[taskId], found));
      if (Object.keys(TASK_STATUS).indexOf(merged.status) === -1) {
        merged.status = TASK_STATUS.pending;
      }
      recoveredTasks[taskId] = merged;
    }

    tasksById = recoveredTasks;

    var candidate = corruptSnapshot && corruptSnapshot.workflow && corruptSnapshot.workflow.status;
    if (typeof candidate === "string" && Object.keys(WORKFLOW_STATUS).indexOf(candidate) >= 0) {
      status = candidate;
    } else {
      status = WORKFLOW_STATUS.pending;
    }

    appendTimeline("workflow-recovered", {
      recoveredAt: Date.now(),
      sourceHadTasks: inputTasks.length,
      status: status,
    });

    return snapshot();
  }

  return {
    workflowId: workflow.id,
    get workflow() {
      return workflow;
    },
    get status() {
      return status;
    },
    setWorkflowStatus: setWorkflowStatus,
    setTaskStatus: setTaskStatus,
    getTask: getTask,
    listTasks: listTasks,
    counts: counts,
    snapshot: snapshot,
    recover: recover,
  };
}

module.exports = {
  createWorkflowState: createWorkflowState,
};
