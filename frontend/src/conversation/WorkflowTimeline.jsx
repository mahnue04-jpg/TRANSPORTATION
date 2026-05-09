"use strict";

function buildWorkflowTimelineModel(workflowResult) {
  var source = workflowResult || {};
  var snapshot = source.snapshot || { tasks: [] };
  var tasks = Array.isArray(snapshot.tasks) ? snapshot.tasks : [];

  var nodes = [];
  var edges = [];
  var retries = 0;
  var progress = { total: tasks.length, completed: 0, failed: 0, cancelled: 0, running: 0 };

  for (var i = 0; i < tasks.length; i++) {
    var task = tasks[i];
    nodes.push({
      id: task.id,
      label: task.type,
      status: task.status,
      tool: task.assignedTool || null,
      retries: task.retries && task.retries.attempted ? task.retries.attempted : 0,
    });

    if (task.status === "completed") {
      progress.completed += 1;
    } else if (task.status === "failed") {
      progress.failed += 1;
    } else if (task.status === "cancelled") {
      progress.cancelled += 1;
    } else if (task.status === "running") {
      progress.running += 1;
    }

    retries += task.retries && task.retries.attempted ? task.retries.attempted : 0;

    for (var j = 0; j < (task.dependencies || []).length; j++) {
      edges.push({ from: task.dependencies[j], to: task.id, type: "dependency" });
    }
  }

  var percent = progress.total === 0 ? 0 : Math.round((progress.completed / progress.total) * 100);

  return {
    workflowId: source.workflowId || (snapshot.workflow ? snapshot.workflow.id : null),
    status: source.status || (snapshot.workflow ? snapshot.workflow.status : "unknown"),
    nodes: nodes,
    edges: edges,
    retries: retries,
    progress: progress,
    progressPercent: percent,
  };
}

function WorkflowTimeline(props) {
  var model = buildWorkflowTimelineModel(props && props.workflowResult ? props.workflowResult : null);
  return {
    type: "WorkflowTimeline",
    model: model,
  };
}

module.exports = {
  WorkflowTimeline: WorkflowTimeline,
  buildWorkflowTimelineModel: buildWorkflowTimelineModel,
};
