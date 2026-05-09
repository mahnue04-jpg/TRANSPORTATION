"use strict";

const { dedupeMemories, rankMemories } = require("./memoryRanker");

function createMemoryRetriever(options) {
  var config = Object.assign(
    {
      shortTermMemory: null,
      semanticMemory: null,
      store: null,
    },
    options || {}
  );

  async function retrieve(query, options) {
    var criteria = options || {};
    var shortTermResults = [];
    var semanticResults = [];

    if (config.shortTermMemory && typeof config.shortTermMemory.list === "function") {
      shortTermResults = config.shortTermMemory.list({ sessionId: criteria.sessionId, type: criteria.type });
    }
    if (config.semanticMemory && typeof config.semanticMemory.search === "function") {
      semanticResults = await config.semanticMemory.search(query, { limit: criteria.limit || 10, weights: criteria.weights });
    }

    var merged = dedupeMemories(shortTermResults.concat(semanticResults));
    var ranked = rankMemories(merged, query, criteria);
    var limit = Math.max(1, criteria.limit || 10);
    return {
      query: query,
      total: ranked.length,
      items: ranked.slice(0, limit),
      shortTermCount: shortTermResults.length,
      semanticCount: semanticResults.length,
    };
  }

  return {
    config: config,
    retrieve: retrieve,
  };
}

module.exports = { createMemoryRetriever: createMemoryRetriever };