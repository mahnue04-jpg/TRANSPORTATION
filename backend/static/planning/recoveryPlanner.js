"use strict";

const { TASK_STATUS } = require("./planningSchemas");

function createRecoveryPlanner(options) {
  var config = Object.assign(
    {
      defaultRetryBackoffMs: 100,
      maxTotalRetries: 50,
      allowFallback: true,
      allowPartialContinuation: true,
    },
    options || {}
  );

  function planRetry(task, error) {
    var retries = task.retries || { attempted: 0, max: 0, backoffMs: config.defaultRetryBackoffMs };
    var attempted = typeof retries.attempted === "number" ? retries.attempted : 0;
    var max = typeof retries.max === "number" ? retries.max : 0;

    if (attempted >= max) {
      return { shouldRetry: false, delayMs: 0, reason: "retry-max-reached", error: error || null };
    }

    var baseDelay = typeof retries.backoffMs === "number" ? retries.backoffMs : config.defaultRetryBackoffMs;
    var delay = baseDelay * Math.pow(2, attempted);

    return {
      shouldRetry: true,
      delayMs: Math.min(5000, delay),
      reason: "retryable-error",
      nextAttempt: attempted + 1,
      error: error || null,
    };
  }

  function planFallback(task, state, graph) {
    if (!config.allowFallback || !task.fallbackTaskId) {
      return { useFallback: false };
    }

    var fallbackTask = state.getTask(task.fallbackTaskId);
    if (!fallbackTask) {
      return { useFallback: false, reason: "missing-fallback-task" };
    }

    var dependencies = graph.getDependencies(fallbackTask.id);
    for (var i = 0; i < dependencies.length; i++) {
      var depTask = state.getTask(dependencies[i]);
      if (!depTask || depTask.status !== TASK_STATUS.completed) {
        return { useFallback: false, reason: "fallback-dependencies-not-ready" };
      }
    }

    if (fallbackTask.status === TASK_STATUS.completed) {
      return { useFallback: true, fallbackTaskId: fallbackTask.id, alreadyCompleted: true };
    }

    if (fallbackTask.status === TASK_STATUS.failed || fallbackTask.status === TASK_STATUS.cancelled) {
      return { useFallback: false, reason: "fallback-already-terminal" };
    }

    return { useFallback: true, fallbackTaskId: fallbackTask.id, alreadyCompleted: false };
  }

  function planPartialContinuation(state, graph, failedTaskId) {
    if (!config.allowPartialContinuation) {
      return { continuable: false, blockedTasks: graph.getDependents(failedTaskId) };
    }

    var blocked = [];
    var continuable = [];
    var dependents = graph.getDependents(failedTaskId);

    for (var i = 0; i < dependents.length; i++) {
      var dependentTask = state.getTask(dependents[i]);
      if (!dependentTask) {
        continue;
      }
      if (dependentTask.allowPartialContinuation) {
        continuable.push(dependentTask.id);
      } else {
        blocked.push(dependentTask.id);
      }
    }

    return {
      continuable: blocked.length === 0,
      continuableTasks: continuable,
      blockedTasks: blocked,
    };
  }

  return {
    config: config,
    planRetry: planRetry,
    planFallback: planFallback,
    planPartialContinuation: planPartialContinuation,
  };
}

module.exports = {
  createRecoveryPlanner: createRecoveryPlanner,
};
