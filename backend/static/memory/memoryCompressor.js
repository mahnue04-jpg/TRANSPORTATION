"use strict";

const { estimateTokens, rankMemories, dedupeMemories, filterStaleMemories } = require("./memoryRanker");
const { summarizeMemories } = require("./memorySummarizer");

function totalTokens(memories) {
  return (memories || []).reduce(function (sum, memory) {
    return sum + estimateTokens(memory.content);
  }, 0);
}

function compressMemories(memories, options) {
  var config = options || {};
  var budgetTokens = config.maxTokens || 800;
  var query = config.query || "";
  var ranked = rankMemories(filterStaleMemories(dedupeMemories(memories), config), query, config);
  var retained = [];
  var dropped = [];

  ranked.forEach(function (memory) {
    var tokenCost = estimateTokens(memory.content);
    if (totalTokens(retained) + tokenCost <= budgetTokens) {
      retained.push(memory);
    } else {
      dropped.push(memory);
    }
  });

  var summary = null;
  if (dropped.length > 0) {
    var summaryBudget = Math.max(60, (budgetTokens - totalTokens(retained)) * 4);
    summary = summarizeMemories(dropped, Object.assign({}, config, { maxChars: summaryBudget }));
    while (retained.length > 0 && totalTokens(retained) + summary.tokens > budgetTokens) {
      dropped.unshift(retained.pop());
      summaryBudget = Math.max(60, (budgetTokens - totalTokens(retained)) * 4);
      summary = summarizeMemories(dropped, Object.assign({}, config, { maxChars: summaryBudget }));
    }
  }

  return {
    retained: retained,
    dropped: dropped,
    summary: summary,
    consumedTokens: totalTokens(retained) + (summary ? summary.tokens : 0),
    budgetTokens: budgetTokens,
    truncated: dropped.length > 0,
  };
}

module.exports = { compressMemories: compressMemories };