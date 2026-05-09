"use strict";

const { createMemoryEntry } = require("./memorySchemas");
const { rankMemories } = require("./memoryRanker");

function createMockEmbeddingProvider(options) {
  var config = Object.assign({ dimensions: 16 }, options || {});

  function embedSync(text) {
    var vector = new Array(config.dimensions).fill(0);
    var source = String(text || "");
    for (var index = 0; index < source.length; index++) {
      vector[index % config.dimensions] += source.charCodeAt(index) / 255;
    }
    return vector;
  }

  return {
    dimensions: config.dimensions,
    embedSync: embedSync,
    embed: async function (text) {
      return embedSync(text);
    },
  };
}

function createSemanticMemory(options) {
  var config = Object.assign(
    {
      store: null,
      embeddingProvider: createMockEmbeddingProvider(),
      vectorAdapter: null,
    },
    options || {}
  );

  var index = [];

  async function upsertMemory(input) {
    var entry = createMemoryEntry(input);
    if (config.embeddingProvider && typeof config.embeddingProvider.embed === "function") {
      entry.embedding = await config.embeddingProvider.embed(JSON.stringify(entry.content || ""));
    }
    index = index.filter(function (item) { return item.id !== entry.id; }).concat([entry]);
    if (config.store && typeof config.store.upsert === "function") {
      await config.store.upsert(entry);
    }
    return entry;
  }

  async function search(query, options) {
    var configOptions = options || {};
    var ranked = rankMemories(index, query, {
      embeddingProvider: config.embeddingProvider,
      weights: configOptions.weights,
      recencyHalfLifeMs: configOptions.recencyHalfLifeMs,
      frequencyScale: configOptions.frequencyScale,
    });
    return ranked.slice(0, configOptions.limit || 10);
  }

  function list() {
    return index.slice();
  }

  function clear() {
    index = [];
    return index.slice();
  }

  return {
    config: config,
    upsertMemory: upsertMemory,
    search: search,
    list: list,
    clear: clear,
  };
}

module.exports = {
  createSemanticMemory: createSemanticMemory,
  createMockEmbeddingProvider: createMockEmbeddingProvider,
};