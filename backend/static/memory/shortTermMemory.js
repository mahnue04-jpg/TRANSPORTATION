"use strict";

const { createMemoryEntry } = require("./memorySchemas");
const { dedupeMemories, filterStaleMemories } = require("./memoryRanker");

function createShortTermMemory(options) {
  var config = Object.assign(
    {
      maxEntries: 50,
      ttlMs: 1000 * 60 * 30,
      sessionId: null,
      store: null,
    },
    options || {}
  );

  var entries = [];

  function prune() {
    entries = filterStaleMemories(entries, { ttlMs: config.ttlMs });
    if (entries.length > config.maxEntries) {
      entries = entries.slice(entries.length - config.maxEntries);
    }
    entries = dedupeMemories(entries);
    return entries.slice();
  }

  async function addMemory(input) {
    var entry = createMemoryEntry(Object.assign({}, input || {}, {
      scope: "session",
      sessionId: input && input.sessionId ? input.sessionId : config.sessionId,
    }));
    entries.push(entry);
    prune();
    if (config.store && typeof config.store.upsert === "function") {
      await config.store.upsert(entry);
    }
    return entry;
  }

  function list(filter) {
    var criteria = filter || {};
    return prune().filter(function (entry) {
      if (criteria.sessionId && entry.sessionId !== criteria.sessionId) return false;
      if (criteria.type && entry.type !== criteria.type) return false;
      return true;
    });
  }

  function recent(limit) {
    return prune().slice(-Math.max(1, limit || 10));
  }

  function clear() {
    entries = [];
    return entries.slice();
  }

  return {
    config: config,
    addMemory: addMemory,
    list: list,
    recent: recent,
    prune: prune,
    clear: clear,
  };
}

module.exports = { createShortTermMemory: createShortTermMemory };