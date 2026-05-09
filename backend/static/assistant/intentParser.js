"use strict";

function classifyIntent(clause) {
  var text = String(clause || "").toLowerCase();

  if (/weather|forecast|temperature/.test(text)) {
    return { type: "weather", taskType: "search" };
  }
  if (/search|find|look up|lookup/.test(text)) {
    return { type: "search", taskType: "search" };
  }
  if (/write|summarize|compose|respond/.test(text)) {
    return { type: "compose", taskType: "io" };
  }
  if (/news|headlines/.test(text)) {
    return { type: "news", taskType: "search" };
  }

  return { type: "generic", taskType: "generic" };
}

function detectConflicts(intents) {
  var conflicts = [];
  var seenTypes = Object.create(null);

  for (var i = 0; i < intents.length; i++) {
    var key = intents[i].type + "::" + intents[i].clause;
    if (seenTypes[key]) {
      conflicts.push({
        code: "duplicate-intent",
        message: "Duplicate clause detected: " + intents[i].clause,
        clause: intents[i].clause,
      });
    }
    seenTypes[key] = true;
  }

  var hasCancel = intents.some(function (item) { return /cancel|stop|abort/.test(item.clause.toLowerCase()); });
  var hasExecute = intents.some(function (item) { return !/cancel|stop|abort/.test(item.clause.toLowerCase()); });
  if (hasCancel && hasExecute) {
    conflicts.push({
      code: "conflicting-intents",
      message: "Goal contains both cancellation and execution directives",
    });
  }

  return conflicts;
}

function parseIntent(interpretedGoal) {
  var clauses = Array.isArray(interpretedGoal && interpretedGoal.clauses) ? interpretedGoal.clauses : [];
  var intents = [];

  for (var i = 0; i < clauses.length; i++) {
    var cls = classifyIntent(clauses[i]);
    intents.push({
      id: "intent-" + (i + 1),
      clause: clauses[i],
      type: cls.type,
      taskType: cls.taskType,
      priority: 100 - i,
    });
  }

  var conflicts = detectConflicts(intents);
  return {
    intents: intents,
    conflicts: conflicts,
    valid: conflicts.length === 0,
  };
}

module.exports = {
  parseIntent: parseIntent,
};
