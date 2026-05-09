"use strict";

const fs = require("fs/promises");
const os = require("os");
const path = require("path");

const {
  createMemoryManager,
  createMemoryStore,
  createMemoryEntry,
  MEMORY_TYPES,
  summarizeText,
  rankMemories,
  dedupeMemories,
  filterStaleMemories,
} = require("./memory");

async function runMemoryTests() {
  var tests = [];
  var passed = 0;
  var failed = 0;

  function test(name, fn) {
    tests.push({ name: name, fn: fn });
  }

  function ok(condition, message) {
    if (!condition) {
      failed += 1;
      console.error("  ✗ FAIL: " + message);
      return false;
    }
    passed += 1;
    console.log("  ✓ " + message);
    return true;
  }

  async function withTempManager(fn, options) {
    var root = await fs.mkdtemp(path.join(os.tmpdir(), "amicore-memory-"));
    var storagePath = path.join(root, "memory.json");
    var manager = createMemoryManager(Object.assign({ storagePath: storagePath, persist: true, sessionId: "session-1" }, options || {}));
    try {
      await fn(manager, root, storagePath);
    } finally {
      await fs.rm(root, { recursive: true, force: true }).catch(function () {});
    }
  }

  test("memory overflow compresses context", async function () {
    await withTempManager(async function (manager) {
      for (var index = 0; index < 40; index++) {
        await manager.addConversationMemory("conversation item " + index + " " + new Array(40).join("x"), { frequency: index % 5 });
      }
      var assembled = await manager.assembleContext({ query: "conversation", maxTokens: 120 });
      ok(assembled.context.length > 0, "context was assembled");
      ok(assembled.compressed.consumedTokens <= assembled.maxTokens, "token budget respected");
    });
  });

  test("retrieval ranking prefers relevant memories", async function () {
    var memories = [
      createMemoryEntry({ id: "a", type: MEMORY_TYPES.conversation, content: "banana recipe", importance: 0.2, timestamp: Date.now() - 1000 }),
      createMemoryEntry({ id: "b", type: MEMORY_TYPES.conversation, content: "apple pie recipe", importance: 0.9, timestamp: Date.now() - 5000 }),
      createMemoryEntry({ id: "c", type: MEMORY_TYPES.conversation, content: "oranges and pears", importance: 0.1, timestamp: Date.now() - 100 }),
    ];
    var ranked = rankMemories(memories, "apple recipe", {});
    ok(ranked[0].id === "b" || ranked[0].id === "a", "relevant memory ranked near the top");
  });

  test("summarization returns concise output", async function () {
    var summary = summarizeText("One. Two. Three. Four.", { maxSentences: 2, maxChars: 80 });
    ok(summary.summary.indexOf("One") !== -1 && summary.summary.indexOf("Two") !== -1, "summary contains first sentences");
    ok(summary.sentences === 2, "summary respected sentence limit");
  });

  test("concurrent writes are serialized safely", async function () {
    await withTempManager(async function (manager) {
      var tasks = [];
      for (var index = 0; index < 30; index++) {
        tasks.push(manager.addToolExecutionMemory({ index: index, status: "completed" }, { executionIndex: index }));
      }
      var results = await Promise.all(tasks);
      ok(results.length === 30, "all concurrent writes resolved");
      var assembled = await manager.retrieve("completed", { limit: 50 });
      ok(assembled.total >= 30, "store retained concurrent writes");
    });
  });

  test("corruption recovery resets invalid store", async function () {
    var root = await fs.mkdtemp(path.join(os.tmpdir(), "amicore-memory-corrupt-"));
    var storagePath = path.join(root, "memory.json");
    await fs.writeFile(storagePath, "not-json", "utf8");
    var store = createMemoryStore({ storagePath: storagePath, persist: true });
    await store.load();
    var snapshot = store.snapshot();
    ok(snapshot.total === 0, "corrupt store was reset");
    await fs.rm(root, { recursive: true, force: true }).catch(function () {});
  });

  test("token budgeting respects limits", async function () {
    await withTempManager(async function (manager) {
      for (var index = 0; index < 12; index++) {
        await manager.addWorkflowMemory("workflow step " + index + " " + new Array(80).join("w"), { frequency: 1 });
      }
      var retrieved = await manager.retrieve("workflow", { limit: 20 });
      var compressed = await manager.compress(retrieved.items);
      ok(compressed.consumedTokens <= manager.config.maxTokens, "compression stayed within token budget");
    }, { maxTokens: 100 });
  });

  test("duplicate suppression removes repeats", async function () {
    var duplicates = dedupeMemories([
      createMemoryEntry({ id: "1", type: MEMORY_TYPES.user_preference, content: "dark mode" }),
      createMemoryEntry({ id: "2", type: MEMORY_TYPES.user_preference, content: "dark mode" }),
      createMemoryEntry({ id: "3", type: MEMORY_TYPES.user_preference, content: "light mode" }),
    ]);
    ok(duplicates.length === 2, "duplicate memory removed");
  });

  test("stale memory cleanup removes expired entries", async function () {
    var entries = filterStaleMemories([
      createMemoryEntry({ id: "old", type: MEMORY_TYPES.system_state, content: "stale", timestamp: Date.now() - 1000 * 60 * 60 * 24 * 30 }),
      createMemoryEntry({ id: "new", type: MEMORY_TYPES.system_state, content: "fresh", timestamp: Date.now() }),
    ], { ttlMs: 1000 * 60 * 60 * 24 * 7 });
    ok(entries.length === 1 && entries[0].id === "new", "stale entry removed");
  });

  for (var i = 0; i < tests.length; i++) {
    console.log("  ● " + tests[i].name);
    try {
      await tests[i].fn();
    } catch (error) {
      failed += 1;
      console.error("    ERROR: " + error.message);
    }
  }

  return { passed: passed, failed: failed, total: passed + failed };
}

module.exports = { runMemoryTests: runMemoryTests };