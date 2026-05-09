"use strict";

function buildTaskManagerWorkflow(input, context) {
  var payload = input.payload || {};
  var tasks = Array.isArray(payload.tasks) ? payload.tasks : [];

  return {
    capability: "taskManager",
    summary: "Generated task management workflow with prioritization and follow-up",
    goal: input.goal || "Organize and prioritize tasks",
    tasks: [
      { id: "task-capture", type: "document", priority: 90, input: { tasks: tasks } },
      { id: "task-priority", type: "io", priority: 86, dependencies: ["task-capture"], input: { strategy: payload.strategy || "impact-effort" } },
      { id: "task-plan", type: "io", priority: 82, dependencies: ["task-priority"], input: { includeDeadlines: !!payload.includeDeadlines } },
      { id: "task-review", type: "io", priority: 78, dependencies: ["task-plan"], input: { cadence: payload.reviewCadence || "weekly" } },
    ],
    context: {
      memorySummary: context.memorySummary || "",
      continuityHint: "Task continuity enabled",
    },
  };
}

module.exports = {
  buildTaskManagerWorkflow: buildTaskManagerWorkflow,
};
