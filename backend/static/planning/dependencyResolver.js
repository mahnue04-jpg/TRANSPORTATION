"use strict";

const { TASK_STATUS } = require("./planningSchemas");

function sortTasks(tasks) {
  return tasks.slice().sort(function (a, b) {
    if (b.priority !== a.priority) {
      return b.priority - a.priority;
    }
    return a.id.localeCompare(b.id);
  });
}

function dependencySatisfied(dependencyTask, dependentTask) {
  if (!dependencyTask) {
    return false;
  }
  if (dependencyTask.status === TASK_STATUS.completed) {
    return true;
  }
  if (dependencyTask.status === TASK_STATUS.cancelled && dependentTask && dependentTask.allowPartialContinuation) {
    return true;
  }
  if (dependencyTask.status === TASK_STATUS.failed && dependentTask && dependentTask.allowPartialContinuation) {
    return true;
  }
  return false;
}

function resolveDependencies(graph, state) {
  var ready = [];
  var blocked = [];
  var unresolved = [];

  for (var i = 0; i < graph.ids.length; i++) {
    var taskId = graph.ids[i];
    var task = state.getTask(taskId);

    if (!task) {
      continue;
    }

    if (task.status === TASK_STATUS.completed || task.status === TASK_STATUS.failed || task.status === TASK_STATUS.cancelled || task.status === TASK_STATUS.running) {
      continue;
    }

    var dependencies = graph.getDependencies(taskId);
    var unmet = [];
    for (var j = 0; j < dependencies.length; j++) {
      var depTask = state.getTask(dependencies[j]);
      if (!dependencySatisfied(depTask, task)) {
        unmet.push(dependencies[j]);
      }
    }

    if (unmet.length === 0) {
      ready.push(task);
    } else {
      blocked.push({ task: task, unmet: unmet });
      unresolved.push({ taskId: task.id, unmet: unmet });
    }
  }

  return {
    ready: sortTasks(ready),
    blocked: blocked,
    unresolved: unresolved,
  };
}

module.exports = {
  resolveDependencies: resolveDependencies,
  sortTasks: sortTasks,
};
