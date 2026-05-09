"use strict";

function normalizeText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function splitClauses(goal) {
  var text = normalizeText(goal);
  if (!text) {
    return [];
  }
  return text
    .split(/(?:\.|,|\bthen\b|\band\b|\bafter\b)/gi)
    .map(function (part) { return part.trim(); })
    .filter(function (part) { return part.length > 0; });
}

function interpretGoal(input) {
  var goal = normalizeText(input);
  if (!goal) {
    return {
      valid: false,
      error: "empty-goal",
      normalizedGoal: "",
      clauses: [],
      inferredObjectives: [],
      requiresPlanning: false,
    };
  }

  var clauses = splitClauses(goal);
  var inferredObjectives = [];
  for (var i = 0; i < clauses.length; i++) {
    inferredObjectives.push({
      id: "objective-" + (i + 1),
      text: clauses[i],
      priority: 100 - i,
    });
  }

  return {
    valid: true,
    normalizedGoal: goal,
    clauses: clauses,
    inferredObjectives: inferredObjectives,
    requiresPlanning: clauses.length > 1 || goal.length > 48,
  };
}

module.exports = {
  interpretGoal: interpretGoal,
};
