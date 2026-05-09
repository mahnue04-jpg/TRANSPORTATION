"use strict";

function buildSchedulingWorkflow(input, context) {
  var payload = input.payload || {};
  return {
    capability: "schedulingAssistant",
    summary: "Prepared scheduling workflow with conflict checks and outreach draft",
    goal: input.goal || "Coordinate schedules and propose meeting times",
    tasks: [
      { id: "schedule-collect", type: "document", priority: 90, input: { participants: payload.participants || [] } },
      { id: "schedule-conflicts", type: "io", priority: 87, dependencies: ["schedule-collect"], input: { constraints: payload.constraints || [] } },
      { id: "schedule-proposals", type: "io", priority: 84, dependencies: ["schedule-conflicts"], input: { slotCount: payload.slotCount || 3 } },
      { id: "schedule-invite", type: "io", priority: 80, dependencies: ["schedule-proposals"], input: { tone: payload.tone || "professional" } },
    ],
    context: {
      memorySummary: context.memorySummary || "",
      retrievedMemories: context.retrievedMemories || [],
    },
  };
}

module.exports = {
  buildSchedulingWorkflow: buildSchedulingWorkflow,
};
