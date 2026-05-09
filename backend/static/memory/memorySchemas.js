"use strict";

const crypto = require("crypto");

var MEMORY_TYPES = Object.freeze({
  conversation: "conversation",
  tool_execution: "tool_execution",
  workflow: "workflow",
  user_preference: "user_preference",
  system_state: "system_state",
  session: "session",
});

function createId() {
  if (crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return "mem-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
}

function clone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

function normalizeImportance(value) {
  var numeric = Number(value);
  if (!isFinite(numeric)) {
    numeric = 0.5;
  }
  if (numeric < 0) numeric = 0;
  if (numeric > 1) numeric = 1;
  return numeric;
}

function createMemoryEntry(input) {
  var source = input || {};
  var entry = {
    id: source.id || createId(),
    type: source.type || MEMORY_TYPES.conversation,
    timestamp: source.timestamp || Date.now(),
    importance: normalizeImportance(source.importance),
    source: source.source || "unknown",
    content: source.content !== undefined ? clone(source.content) : null,
    embedding: source.embedding !== undefined ? clone(source.embedding) : null,
    metadata: source.metadata ? clone(source.metadata) : {},
    scope: source.scope || "persistent",
    sessionId: source.sessionId || null,
  };
  if (!entry.metadata) {
    entry.metadata = {};
  }
  return entry;
}

function validateMemoryEntry(entry) {
  if (!entry || typeof entry !== "object") {
    throw new Error("Memory entry must be an object");
  }
  if (!entry.id) {
    throw new Error("Memory entry requires an id");
  }
  if (!entry.type) {
    throw new Error("Memory entry requires a type");
  }
  if (!entry.timestamp) {
    throw new Error("Memory entry requires a timestamp");
  }
  return true;
}

function cloneMemoryEntry(entry) {
  return createMemoryEntry(entry);
}

module.exports = {
  MEMORY_TYPES: MEMORY_TYPES,
  createId: createId,
  createMemoryEntry: createMemoryEntry,
  validateMemoryEntry: validateMemoryEntry,
  cloneMemoryEntry: cloneMemoryEntry,
  normalizeImportance: normalizeImportance,
};