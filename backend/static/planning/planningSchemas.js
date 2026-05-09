"use strict";

const TASK_STATUS = {
  pending: "pending",
  ready: "ready",
  running: "running",
  blocked: "blocked",
  failed: "failed",
  completed: "completed",
  cancelled: "cancelled",
};

const WORKFLOW_STATUS = {
  pending: "pending",
  ready: "ready",
  running: "running",
  blocked: "blocked",
  failed: "failed",
  completed: "completed",
  cancelled: "cancelled",
};

const VALID_TASK_STATUSES = Object.keys(TASK_STATUS);
const VALID_WORKFLOW_STATUSES = Object.keys(WORKFLOW_STATUS);

function uid(prefix) {
  return String(prefix || "wf") + "-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
}

function normalizePriority(priority) {
  if (typeof priority !== "number" || !isFinite(priority)) {
    return 50;
  }
  return Math.max(0, Math.min(100, Math.floor(priority)));
}

function normalizeDependencies(dependencies) {
  if (!Array.isArray(dependencies)) {
    return [];
  }
  var unique = Object.create(null);
  var normalized = [];
  for (var i = 0; i < dependencies.length; i++) {
    var dep = String(dependencies[i] || "").trim();
    if (!dep || unique[dep]) {
      continue;
    }
    unique[dep] = true;
    normalized.push(dep);
  }
  return normalized;
}

function clone(value) {
  if (value === null || value === undefined) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(clone);
  }
  if (typeof value === "object") {
    var out = {};
    var keys = Object.keys(value);
    for (var i = 0; i < keys.length; i++) {
      out[keys[i]] = clone(value[keys[i]]);
    }
    return out;
  }
  return value;
}

function createTask(input) {
  var source = input || {};
  var retriesInput = source.retries || {};
  var task = {
    id: String(source.id || uid("task")),
    type: String(source.type || "generic"),
    dependencies: normalizeDependencies(source.dependencies),
    priority: normalizePriority(source.priority),
    status: VALID_TASK_STATUSES.indexOf(source.status) >= 0 ? source.status : TASK_STATUS.pending,
    retries: {
      attempted: typeof retriesInput.attempted === "number" ? Math.max(0, retriesInput.attempted) : 0,
      max: typeof retriesInput.max === "number" ? Math.max(0, retriesInput.max) : 2,
      backoffMs: typeof retriesInput.backoffMs === "number" ? Math.max(0, retriesInput.backoffMs) : 100,
    },
    assignedTool: source.assignedTool ? String(source.assignedTool) : null,
    context: clone(source.context || {}),
    outputs: clone(source.outputs || null),
    input: clone(source.input || {}),
    condition: source.condition ? clone(source.condition) : null,
    fallbackTaskId: source.fallbackTaskId ? String(source.fallbackTaskId) : null,
    timeoutMs: typeof source.timeoutMs === "number" ? Math.max(1, source.timeoutMs) : 5000,
    allowPartialContinuation: !!source.allowPartialContinuation,
    metadata: clone(source.metadata || {}),
  };

  return task;
}

function createWorkflow(input) {
  var source = input || {};
  var tasksInput = Array.isArray(source.tasks) ? source.tasks : [];
  var tasks = [];
  for (var i = 0; i < tasksInput.length; i++) {
    tasks.push(createTask(tasksInput[i]));
  }

  var workflow = {
    id: String(source.id || uid("workflow")),
    goal: String(source.goal || ""),
    status: VALID_WORKFLOW_STATUSES.indexOf(source.status) >= 0 ? source.status : WORKFLOW_STATUS.pending,
    createdAt: typeof source.createdAt === "number" ? source.createdAt : Date.now(),
    startedAt: typeof source.startedAt === "number" ? source.startedAt : null,
    completedAt: typeof source.completedAt === "number" ? source.completedAt : null,
    tasks: tasks,
    context: clone(source.context || {}),
    maxDepth: typeof source.maxDepth === "number" ? Math.max(1, source.maxDepth) : 25,
    timeoutBudgetMs: typeof source.timeoutBudgetMs === "number" ? Math.max(1, source.timeoutBudgetMs) : 30000,
    metadata: clone(source.metadata || {}),
  };

  return workflow;
}

function createWorkflowVisualization(workflow) {
  var nodes = [];
  var edges = [];
  var tasks = workflow && Array.isArray(workflow.tasks) ? workflow.tasks : [];

  for (var i = 0; i < tasks.length; i++) {
    nodes.push({
      id: tasks[i].id,
      label: tasks[i].type,
      status: tasks[i].status,
      priority: tasks[i].priority,
      assignedTool: tasks[i].assignedTool,
    });

    for (var j = 0; j < tasks[i].dependencies.length; j++) {
      edges.push({
        from: tasks[i].dependencies[j],
        to: tasks[i].id,
        type: "dependency",
      });
    }
  }

  return {
    schemaVersion: "1.0.0",
    workflowId: workflow ? workflow.id : null,
    workflowStatus: workflow ? workflow.status : null,
    nodes: nodes,
    edges: edges,
    generatedAt: Date.now(),
  };
}

module.exports = {
  TASK_STATUS: TASK_STATUS,
  WORKFLOW_STATUS: WORKFLOW_STATUS,
  VALID_TASK_STATUSES: VALID_TASK_STATUSES,
  VALID_WORKFLOW_STATUSES: VALID_WORKFLOW_STATUSES,
  createTask: createTask,
  createWorkflow: createWorkflow,
  createWorkflowVisualization: createWorkflowVisualization,
  normalizeDependencies: normalizeDependencies,
  normalizePriority: normalizePriority,
  clonePlanningValue: clone,
};
