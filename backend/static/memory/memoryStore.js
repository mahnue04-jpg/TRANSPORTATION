"use strict";

const fs = require("fs/promises");
const path = require("path");

const { createMemoryEntry, validateMemoryEntry, cloneMemoryEntry } = require("./memorySchemas");

function createMemoryStore(options) {
  var config = Object.assign(
    {
      storagePath: null,
      persist: true,
    },
    options || {}
  );

  var records = new Map();
  var writeChain = Promise.resolve();

  function enqueue(operation) {
    writeChain = writeChain.then(operation, operation);
    return writeChain;
  }

  async function ensureDirectory() {
    if (!config.storagePath) {
      return;
    }
    await fs.mkdir(path.dirname(config.storagePath), { recursive: true });
  }

  async function load() {
    if (!config.persist || !config.storagePath) {
      return snapshot();
    }
    try {
      var raw = await fs.readFile(config.storagePath, "utf8");
      var parsed = JSON.parse(raw);
      records.clear();
      (parsed.entries || []).forEach(function (entry) {
        var normalized = createMemoryEntry(entry);
        records.set(normalized.id, normalized);
      });
      return snapshot();
    } catch (error) {
      if (error && error.code === "ENOENT") {
        return snapshot();
      }
      if (config.storagePath) {
        try {
          await fs.rename(config.storagePath, config.storagePath + ".corrupt");
        } catch (_) {}
      }
      records.clear();
      return snapshot();
    }
  }

  async function save() {
    if (!config.persist || !config.storagePath) {
      return snapshot();
    }
    await ensureDirectory();
    var payload = JSON.stringify(snapshot(), null, 2);
    await fs.writeFile(config.storagePath, payload, "utf8");
    return snapshot();
  }

  function snapshot() {
    return {
      entries: Array.from(records.values()).map(function (entry) {
        return cloneMemoryEntry(entry);
      }),
      total: records.size,
    };
  }

  async function upsert(entry) {
    return enqueue(async function () {
      var normalized = createMemoryEntry(entry);
      validateMemoryEntry(normalized);
      records.set(normalized.id, normalized);
      await save();
      return cloneMemoryEntry(normalized);
    });
  }

  async function bulkUpsert(entries) {
    return enqueue(async function () {
      var results = [];
      (entries || []).forEach(function (entry) {
        var normalized = createMemoryEntry(entry);
        validateMemoryEntry(normalized);
        records.set(normalized.id, normalized);
        results.push(cloneMemoryEntry(normalized));
      });
      await save();
      return results;
    });
  }

  async function remove(id) {
    return enqueue(async function () {
      var deleted = records.delete(id);
      await save();
      return deleted;
    });
  }

  async function clear() {
    return enqueue(async function () {
      records.clear();
      await save();
      return snapshot();
    });
  }

  function list(filter) {
    var criteria = filter || {};
    return Array.from(records.values())
      .filter(function (entry) {
        if (criteria.scope && entry.scope !== criteria.scope) return false;
        if (criteria.sessionId && entry.sessionId !== criteria.sessionId) return false;
        if (criteria.type && entry.type !== criteria.type) return false;
        if (criteria.before && entry.timestamp >= criteria.before) return false;
        if (criteria.after && entry.timestamp <= criteria.after) return false;
        return true;
      })
      .map(function (entry) {
        return cloneMemoryEntry(entry);
      });
  }

  function getById(id) {
    var entry = records.get(id);
    return entry ? cloneMemoryEntry(entry) : null;
  }

  return {
    config: config,
    load: load,
    save: save,
    upsert: upsert,
    bulkUpsert: bulkUpsert,
    remove: remove,
    clear: clear,
    list: list,
    getById: getById,
    snapshot: snapshot,
  };
}

module.exports = { createMemoryStore: createMemoryStore };