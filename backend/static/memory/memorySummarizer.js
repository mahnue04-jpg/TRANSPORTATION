"use strict";

const { estimateTokens } = require("./memoryRanker");

function formatMemory(memory) {
  var content = typeof memory.content === "string" ? memory.content : JSON.stringify(memory.content || {});
  return "- [" + memory.type + "] " + content;
}

function summarizeMemories(memories, options) {
  var config = options || {};
  var maxChars = config.maxChars || 1200;
  var maxEntries = config.maxEntries || 6;
  var selected = (memories || []).slice(0, maxEntries);
  var lines = selected.map(formatMemory);
  var summary = lines.join("\n");

  if (summary.length > maxChars) {
    summary = summary.slice(0, maxChars - 3) + "...";
  }

  return {
    summary: summary,
    entryCount: selected.length,
    tokens: estimateTokens(summary),
    truncated: selected.length < (memories || []).length || summary.length >= maxChars,
  };
}

function summarizeText(text, options) {
  var config = options || {};
  var maxSentences = config.maxSentences || 3;
  var maxChars = config.maxChars || 800;
  var sentences = String(text || "")
    .split(/(?<=[.!?])\s+|\n+/)
    .map(function (sentence) { return sentence.trim(); })
    .filter(Boolean)
    .slice(0, maxSentences);
  var summary = sentences.join(" ");
  if (summary.length > maxChars) {
    summary = summary.slice(0, maxChars - 3) + "...";
  }
  return {
    summary: summary,
    sentences: sentences.length,
    tokens: estimateTokens(summary),
  };
}

module.exports = {
  summarizeMemories: summarizeMemories,
  summarizeText: summarizeText,
};