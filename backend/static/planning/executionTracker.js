"use strict";

function createExecutionTracker(workflowId) {
  var sequence = 0;
  var events = [];
  var taskAttempts = Object.create(null);

  function record(event, payload) {
    sequence += 1;
    events.push({
      seq: sequence,
      at: Date.now(),
      workflowId: workflowId,
      event: event,
      payload: payload || {},
    });
  }

  function recordWorkflowStart(context) {
    record("workflow-start", { context: context || {} });
  }

  function recordWorkflowEnd(status, details) {
    record("workflow-end", { status: status, details: details || {} });
  }

  function recordTaskStart(taskId, toolName) {
    taskAttempts[taskId] = (taskAttempts[taskId] || 0) + 1;
    record("task-start", { taskId: taskId, attempt: taskAttempts[taskId], toolName: toolName || null });
  }

  function recordTaskRetry(taskId, reason, delayMs) {
    record("task-retry", { taskId: taskId, reason: reason || "retry", delayMs: delayMs || 0, attempt: taskAttempts[taskId] || 0 });
  }

  function recordTaskComplete(taskId, output) {
    record("task-complete", { taskId: taskId, output: output || null, attempt: taskAttempts[taskId] || 0 });
  }

  function recordTaskFailure(taskId, error) {
    record("task-failure", { taskId: taskId, error: error || null, attempt: taskAttempts[taskId] || 0 });
  }

  function recordTaskCancelled(taskId, reason) {
    record("task-cancelled", { taskId: taskId, reason: reason || "cancelled", attempt: taskAttempts[taskId] || 0 });
  }

  function summary() {
    var stats = {
      workflowId: workflowId,
      events: events.length,
      retries: 0,
      failures: 0,
      completedTasks: 0,
      cancelledTasks: 0,
      attemptsByTask: {},
    };

    var keys = Object.keys(taskAttempts).sort();
    for (var i = 0; i < keys.length; i++) {
      stats.attemptsByTask[keys[i]] = taskAttempts[keys[i]];
    }

    for (var j = 0; j < events.length; j++) {
      if (events[j].event === "task-retry") {
        stats.retries += 1;
      } else if (events[j].event === "task-failure") {
        stats.failures += 1;
      } else if (events[j].event === "task-complete") {
        stats.completedTasks += 1;
      } else if (events[j].event === "task-cancelled") {
        stats.cancelledTasks += 1;
      }
    }

    return stats;
  }

  return {
    record: record,
    recordWorkflowStart: recordWorkflowStart,
    recordWorkflowEnd: recordWorkflowEnd,
    recordTaskStart: recordTaskStart,
    recordTaskRetry: recordTaskRetry,
    recordTaskComplete: recordTaskComplete,
    recordTaskFailure: recordTaskFailure,
    recordTaskCancelled: recordTaskCancelled,
    getEvents: function () {
      return events.slice();
    },
    summary: summary,
  };
}

module.exports = {
  createExecutionTracker: createExecutionTracker,
};
