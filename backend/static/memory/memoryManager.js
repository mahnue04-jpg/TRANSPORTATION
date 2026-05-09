"use strict";

const path = require("path");

const { MEMORY_TYPES, createMemoryEntry } = require("./memorySchemas");
const { createMemoryStore } = require("./memoryStore");
const { createShortTermMemory } = require("./shortTermMemory");
const { createSemanticMemory, createMockEmbeddingProvider } = require("./semanticMemory");
const { createMemoryRetriever } = require("./memoryRetriever");
const { summarizeMemories, summarizeText } = require("./memorySummarizer");
const { compressMemories } = require("./memoryCompressor");
const { createContextAssembler } = require("./contextAssembler");

function createMemoryManager(options) {
  var config = Object.assign(
    {
      sessionId: null,
      storagePath: null,
      persist: true,
      maxTokens: 1200,
      ttlMs: 1000 * 60 * 60 * 24 * 7,
      embeddingProvider: createMockEmbeddingProvider(),
    },
    options || {}
  );

  var store = config.store || createMemoryStore({ storagePath: config.storagePath, persist: config.persist });
  var shortTermMemory = config.shortTermMemory || createShortTermMemory({
    maxEntries: config.maxShortTermEntries || 50,
    ttlMs: config.ttlMs,
    sessionId: config.sessionId,
    store: store,
  });
  var semanticMemory = config.semanticMemory || createSemanticMemory({
    store: store,
    embeddingProvider: config.embeddingProvider,
    vectorAdapter: config.vectorAdapter || null,
  });
  var retriever = createMemoryRetriever({
    shortTermMemory: shortTermMemory,
    semanticMemory: semanticMemory,
    store: store,
  });
  var assembler = createContextAssembler({
    retriever: retriever,
    maxTokens: config.maxTokens,
    compressionOptions: { ttlMs: config.ttlMs },
  });

  async function addMemory(input) {
    var entry = createMemoryEntry(Object.assign({}, input || {}, {
      sessionId: input && input.sessionId ? input.sessionId : config.sessionId,
    }));
    if (entry.scope === "session" || entry.sessionId || entry.type === MEMORY_TYPES.conversation) {
      await shortTermMemory.addMemory(entry);
    }
    await semanticMemory.upsertMemory(entry);
    return entry;
  }

  function makeTypedAdder(type, scope) {
    return function (content, metadata) {
      return addMemory({
        type: type,
        scope: scope,
        content: content,
        source: scope === "session" ? "session" : "system",
        metadata: metadata || {},
        sessionId: config.sessionId,
      });
    };
  }

  async function retrieve(query, options) {
    return retriever.retrieve(query, Object.assign({}, options || {}, { sessionId: config.sessionId }));
  }

  async function assembleContext(input) {
    return assembler.assemble(Object.assign({}, input || {}, { sessionId: config.sessionId, maxTokens: config.maxTokens }));
  }

  async function summarize(input) {
    if (typeof input === "string") {
      return summarizeText(input, {});
    }
    return summarizeMemories(input || [], {});
  }

  async function compress(input) {
    return compressMemories(input || [], { maxTokens: config.maxTokens });
  }

  async function load() {
    return store.load();
  }

  async function save() {
    return store.save();
  }

  async function cleanup() {
    var snapshot = shortTermMemory.prune();
    await store.bulkUpsert(snapshot);
    return snapshot;
  }

  function createSession(sessionId) {
    return createMemoryManager(Object.assign({}, config, {
      sessionId: sessionId,
      storagePath: config.storagePath,
      store: store,
      shortTermMemory: createShortTermMemory({
        maxEntries: config.maxShortTermEntries || 50,
        ttlMs: config.ttlMs,
        sessionId: sessionId,
        store: store,
      }),
      semanticMemory: semanticMemory,
    }));
  }

  return {
    config: config,
    store: store,
    shortTermMemory: shortTermMemory,
    semanticMemory: semanticMemory,
    retriever: retriever,
    assembler: assembler,
    addMemory: addMemory,
    addConversationMemory: makeTypedAdder(MEMORY_TYPES.conversation, "session"),
    addToolExecutionMemory: makeTypedAdder(MEMORY_TYPES.tool_execution, "persistent"),
    addWorkflowMemory: makeTypedAdder(MEMORY_TYPES.workflow, "persistent"),
    addUserPreferenceMemory: makeTypedAdder(MEMORY_TYPES.user_preference, "persistent"),
    addSystemStateMemory: makeTypedAdder(MEMORY_TYPES.system_state, "persistent"),
    retrieve: retrieve,
    assembleContext: assembleContext,
    summarize: summarize,
    compress: compress,
    load: load,
    save: save,
    cleanup: cleanup,
    createSession: createSession,
  };
}

module.exports = { createMemoryManager: createMemoryManager };