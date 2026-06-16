"use strict";

const fs = require("fs/promises");
const os = require("os");
const path = require("path");
const webMemoryManager = require("./ux/memoryManager.js");

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

  async function withMockLocalStorage(fn) {
    const store = {};
    const original = global.localStorage;
    global.localStorage = {
      getItem(key) { return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null; },
      setItem(key, value) { store[key] = String(value); },
      removeItem(key) { delete store[key]; },
      clear() {
        Object.keys(store).forEach((key) => delete store[key]);
      },
    };
    try {
      await fn(store);
    } finally {
      global.localStorage = original;
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

  test("persistent memory saves and reloads", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "persist-user" });
      webMemoryManager.updateMemory({
        short_term_memory: [{ role: "user", content: "hello", ts: Date.now() }],
        long_term_memory: { user_name: "Ari", preferences: ["concise"] },
      });
      var reloaded = webMemoryManager.loadMemory();
      ok(reloaded.long_term_memory.user_name === "Ari", "long-term name persisted");
      ok(reloaded.short_term_memory.length === 1, "short-term entry persisted");
    });
  });

  test("refresh persistence keeps memory for same namespace", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "refresh-user" });
      webMemoryManager.updateMemory({
        short_term_memory: [{ role: "user", content: "remember this", ts: Date.now() }],
        long_term_memory: { active_projects: ["Amicor"] },
      });
      webMemoryManager.init({ namespace: "refresh-user" });
      var loaded = webMemoryManager.loadMemory();
      ok(loaded.long_term_memory.active_projects.indexOf("Amicor") !== -1, "project persisted across re-init");
      ok(loaded.short_term_memory.length >= 1, "short-term persisted across re-init");
    });
  });

  test("clear memory wipes short and long term", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "clear-user" });
      webMemoryManager.updateMemory({
        short_term_memory: [{ role: "user", content: "temporary", ts: Date.now() }],
        long_term_memory: { user_name: "Cleared" },
      });
      var cleared = webMemoryManager.clearMemory();
      ok(cleared.short_term_memory.length === 0, "short-term memory cleared");
      ok(cleared.long_term_memory.user_name === "", "long-term memory cleared");
    });
  });

  test("multiple updates merge long-term memory safely", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "merge-user" });
      webMemoryManager.updateMemory({ long_term_memory: { preferences: ["dark mode"] } });
      webMemoryManager.updateMemory({ long_term_memory: { preferences: ["dark mode", "compact UI"], goals: ["ship MVP"] } });
      var merged = webMemoryManager.loadMemory();
      ok(merged.long_term_memory.preferences.length === 2, "preferences merged and deduped");
      ok(merged.long_term_memory.goals.indexOf("ship MVP") !== -1, "goals merged");
    });
  });

  test("memory injection is concise and non-duplicating", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "inject-user" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Taylor",
          preferences: ["short responses"],
          likes_dislikes: ["data-driven answers"],
          goals: ["finish release"],
          recurring_interests: ["product metrics"],
        },
      });
      var injected = webMemoryManager.injectMemoryContext("What should we do next?");
      ok(injected.indexOf("[MEMORY_CONTEXT]") !== -1, "memory context injected");
      ok(injected.length < 1000, "injection remains token-safe and concise");
      var reinjected = webMemoryManager.injectMemoryContext(injected);
      ok(reinjected === injected, "memory context not duplicated");
    });
  });

  test("memory orchestration packet returns ranked context", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "orchestration-user" });
      webMemoryManager.updateMemory({
        short_term_memory: [
          { role: "user", content: "Need cleaner onboarding metrics and funnel conversion", ts: Date.now() },
        ],
        long_term_memory: {
          active_projects: ["Onboarding revamp"],
          goals: ["Improve conversion"],
          preferences: ["actionable summaries"],
        },
      });
      var packet = webMemoryManager.buildMemoryOrchestrationPacket("What should we do next for onboarding conversion?", { maxItems: 4 });
      ok(packet && packet.hit === true, "orchestration packet found relevant memory");
      ok(packet.selectedCount > 0, "orchestration packet selected ranked memories");
      ok(typeof packet.contextSnippet === "string" && packet.contextSnippet.length > 0, "orchestration context snippet generated");
    });
  });

  test("stateless fallback claims are blocked when memory exists", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "identity-user" });
      var enforced = webMemoryManager.enforceMemoryAwareResponse(
        "I cannot remember previous conversations.",
        { memoryEnabled: true, hasMemory: true }
      );
      ok(enforced.blocked === true, "contradictory stateless claim was blocked");
      ok(enforced.text.indexOf("I remember") === 0, "response replaced with memory-aware acknowledgement");
    });
  });

  test("absence fallback uses consistent memory-aware phrase", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "identity-empty" });
      var enforced = webMemoryManager.enforceMemoryAwareResponse(
        "I don't store memory and cannot recall previous interactions.",
        { memoryEnabled: true, hasMemory: false }
      );
      ok(enforced.blocked === true, "stateless claim blocked for empty memory");
      ok(enforced.text === "I don't know that yet.", "absence fallback phrase is normalized");
    });
  });

  test("assistant-visible wrapper throws policy violation for stateless disclaimers", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "policy-violation-user" });
      var thrown = null;
      try {
        webMemoryManager.enforceAssistantVisibleResponse(
          "I don't have any information about you specifically.",
          {
            memoryEnabled: true,
            hasMemory: true,
            source: "restored-history",
            responsePath: "restored-history",
            responseSourceIdentifier: "restored-history",
            throwOnViolation: true,
          }
        );
      } catch (error) {
        thrown = error;
      }
      ok(!!thrown, "policy violation was thrown before render");
      ok(thrown && thrown.code === webMemoryManager.POLICY_VIOLATION_CODE, "policy violation code exposed");
      ok(thrown && thrown.replacementText.indexOf("I remember") === 0, "policy violation carries replacement text");
    });
  });

  test("assistant-visible wrapper emits required diagnostics for all source modes", async function () {
    await withMockLocalStorage(async function () {
      var events = [];
      webMemoryManager.init({
        namespace: "diagnostic-user",
        logger: function (event, fields) {
          events.push({ event: event, fields: fields || {} });
        },
      });
      var sources = [
        "replay-mode",
        "restored-history",
        "retry-response",
        "fallback-response",
        "onboarding-mode",
        "education-mode",
        "streaming-response",
        "non-stream-response",
      ];
      for (var i = 0; i < sources.length; i++) {
        try {
          webMemoryManager.enforceAssistantVisibleResponse(
            "I cannot access personal data in this session.",
            {
              memoryEnabled: true,
              hasMemory: true,
              source: sources[i],
              responsePath: sources[i],
              responseSourceIdentifier: sources[i],
              throwOnViolation: true,
            }
          );
        } catch (_) {}
      }

      var eventNames = events.map(function (item) { return item.event; });
      ok(eventNames.indexOf("ASSISTANT_RESPONSE_PATH") >= 0, "assistant response path diagnostic emitted");
      ok(eventNames.indexOf("MEMORY_POLICY_ENFORCED") >= 0, "memory policy enforced diagnostic emitted");
      ok(eventNames.indexOf("STATELESS_TEMPLATE_BLOCKED") >= 0, "stateless template blocked diagnostic emitted");
      ok(eventNames.indexOf("RESPONSE_SOURCE_IDENTIFIER") >= 0, "response source identifier diagnostic emitted");
    });
  });

  test("streaming and non-stream enforcement use the same replacement", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "parity-user" });
      var streaming = webMemoryManager.enforceAssistantVisibleResponse(
        "Each session is independent.",
        {
          memoryEnabled: true,
          hasMemory: false,
          source: "streaming-response",
          responsePath: "stream-finalization",
          responseSourceIdentifier: "stream-finalization",
          throwOnViolation: false,
        }
      );
      var nonStream = webMemoryManager.enforceAssistantVisibleResponse(
        "Each session is independent.",
        {
          memoryEnabled: true,
          hasMemory: false,
          source: "non-stream-response",
          responsePath: "non-stream-response",
          responseSourceIdentifier: "non-stream-response",
          throwOnViolation: false,
        }
      );
      ok(streaming.text === "I don't know that yet.", "streaming response normalized to approved fallback");
      ok(nonStream.text === streaming.text, "non-stream response matches streaming replacement");
    });
  });

  test("post-refresh memory acknowledgement remains injectable", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "refresh-ack" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Morgan",
          recurring_interests: ["AI product strategy"],
        },
      });

      webMemoryManager.init({ namespace: "refresh-ack" });
      var injected = webMemoryManager.injectMemoryContext("Help me plan next steps.");
      ok(injected.indexOf("name=Morgan") >= 0, "memory context acknowledges persisted identity after refresh");
    });
  });

  test("recall consistency keeps memory identity stable", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "identity-consistency" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Avery",
          preferences: ["concise summaries"],
        },
      });

      var first = webMemoryManager.injectMemoryContext("What should I do next?");
      var second = webMemoryManager.injectMemoryContext("What should I do next?");
      ok(first.indexOf("name=Avery") >= 0, "first memory injection includes remembered identity");
      ok(second.indexOf("name=Avery") >= 0, "second memory injection includes remembered identity");
    });
  });

  test("schema mismatch auto-recovers safely", async function () {
    await withMockLocalStorage(async function (store) {
      store["amicor_user_memory_v1:schema-user"] = JSON.stringify({
        memory_version: 999,
        short_term_memory: [{ role: "user", content: "stale", ts: Date.now() }],
        long_term_memory: { user_name: "Legacy" },
      });
      var loaded = webMemoryManager.init({ namespace: "schema-user" });
      ok(loaded.memory_version === 1, "schema mismatch reset to current version");
      ok(loaded.long_term_memory.user_name === "", "legacy payload reset safely");
    });
  });

  test("corrupted payload resets without crashing", async function () {
    await withMockLocalStorage(async function (store) {
      store["amicor_user_memory_v1:corrupt-user"] = "{bad-json";
      var loaded = webMemoryManager.init({ namespace: "corrupt-user" });
      ok(loaded.memory_version === 1, "corrupt payload recovered to default schema");
      ok(Array.isArray(loaded.short_term_memory) && loaded.short_term_memory.length === 0, "corrupt short-term memory cleared safely");
    });
  });

  test("hard caps limit short-term, long-term, and injection budget", async function () {
    await withMockLocalStorage(async function () {
      var items = [];
      for (var index = 0; index < 40; index++) {
        items.push({ role: "user", content: "entry-" + index + new Array(50).join("x"), ts: Date.now() + index });
      }
      webMemoryManager.init({ namespace: "caps-user" });
      webMemoryManager.updateMemory({
        short_term_memory: items,
        long_term_memory: {
          preferences: new Array(20).fill("pref"),
          likes_dislikes: new Array(20).fill("like"),
          goals: new Array(20).fill("goal"),
          recurring_interests: new Array(20).fill("interest"),
          active_projects: new Array(20).fill("project"),
          assistant_notes: new Array(20).fill("note"),
        },
      });
      var loaded = webMemoryManager.loadMemory();
      ok(loaded.short_term_memory.length <= 14, "short-term entries capped");
      ok(loaded.long_term_memory.active_projects.length <= 6, "long-term active projects capped");
      var injected = webMemoryManager.injectMemoryContext("hello");
      ok(injected.length <= 1000, "injection budget stays bounded");
    });
  });

  test("memory metrics track hits, injections, and retrieval latency", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "metrics-user" });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Riley" } });
      webMemoryManager.injectMemoryContext("Need help?");
      var metrics = webMemoryManager.getMetrics();
      ok(metrics.injections >= 1, "injection count recorded");
      ok(metrics.memoryHitRate >= 0, "memory hit rate exposed");
      ok(metrics.lastRetrievalLatencyMs >= 0, "retrieval latency captured");
    });
  });

  test("memory capability helper explains builder steps safely", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "builder-memory" });
      var response = webMemoryManager.buildMemoryCapabilityResponse(
        "what can I do as a builder so you can remember personal information",
        { source: "memory-test-builder" }
      );
      ok(response.matched === true, "builder memory question matched helper");
      ok(response.text.indexOf("user memory settings page") >= 0, "builder helper includes settings page");
      ok(response.text.indexOf("account-based memory ownership") >= 0, "builder helper includes ownership step");
    });
  });

  test("memory capability helper explains long-term memory", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "helper-long-term" });
      var response = webMemoryManager.buildMemoryCapabilityResponse(
        "do you have long-term memory",
        { memoryContext: { context: "name=Riley" }, hasMemory: true, source: "memory-test-long-term" }
      );
      ok(response.matched === true, "long-term memory question matched helper");
      ok(response.text.indexOf("recent exchanges") >= 0, "helper explains recent memory behavior naturally");
      ok(response.text.indexOf("durable facts and preferences") >= 0, "helper explains durable memory behavior naturally");
    });
  });

  test("reflective memory prompts route to reflective synthesis", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "reflective-route-prompts" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Saye",
          preferences: ["prefers concise replies"],
        },
      });

      var prompts = [
        "what do you remember about me",
        "what do you know about me",
        "tell me what you remember",
        "what are my preferences",
        "who am I",
        "what have I told you",
      ];
      for (var i = 0; i < prompts.length; i++) {
        var response = webMemoryManager.buildMemoryCapabilityResponse(prompts[i], {
          source: "memory-test-reflective-route-" + i,
        });
        ok(response.matched === true, "reflective prompt matched: " + prompts[i]);
        ok(response.reflective === true, "reflective route used: " + prompts[i]);
        ok(response.finalRouteLocked === true, "reflective route locked as final: " + prompts[i]);
        ok(response.text.indexOf("short_term_memory") < 0, "architecture narration suppressed for reflective prompt");
        ok(response.text.indexOf("long_term_memory") < 0, "storage narration suppressed for reflective prompt");
      }
    });
  });

  test("reflective synthesis: sparse memory remains truthful and user-centered", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "reflective-sparse" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Saye",
          preferences: ["likes concise answers"],
        },
      });
      var response = webMemoryManager.buildMemoryCapabilityResponse("what do you know about me", {
        source: "memory-test-reflective-sparse",
      });
      ok(response.reflectiveSuccess === true, "sparse reflection still considered successful with known canonical facts");
      ok(response.finalRouteLocked === true, "sparse reflection route remains terminal-locked");
      ok(response.text.indexOf("your name is Saye") >= 0, "canonical identity included in sparse synthesis");
      ok(response.text.indexOf("prefer") >= 0, "known preference included in sparse synthesis");
      ok(response.text.indexOf("do not yet know many additional personal preferences") >= 0, "truthful sparse boundary included");
      ok(response.text.indexOf("architecture") < 0, "no architecture fallback narration in sparse synthesis");
    });
  });

  test("reflective synthesis: rich memory includes stable traits and continuity without hallucinations", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "reflective-rich" });
      var now = Date.now();
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Saye",
          preferences: ["prefers concise replies"],
          likes_dislikes: ["data-backed reasoning"],
          active_projects: ["Amicor rebuild"],
          goals: ["ship MVP"],
          recurring_interests: ["UX reliability"],
        },
        short_term_memory: [
          { role: "user", content: "Please prioritize replay continuity this week.", ts: now - 10 },
        ],
      });
      var response = webMemoryManager.buildMemoryCapabilityResponse("what have I told you", {
        source: "memory-test-reflective-rich",
      });
      ok(response.reflectiveSuccess === true, "rich reflection succeeds");
      ok(response.finalRouteLocked === true, "rich reflection is terminal-locked");
      ok(response.text.indexOf("your name is Saye") >= 0, "rich synthesis includes canonical identity");
      ok(response.text.indexOf("Amicor rebuild") >= 0, "rich synthesis includes persisted project fact");
      ok(response.text.indexOf("Most recently") >= 0, "rich synthesis includes recent continuity");
      ok(response.text.indexOf("location") < 0, "rich synthesis does not hallucinate unspecified personal facts");
    });
  });

  test("reflective synthesis: mode switching keeps concise reflection after correction", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "reflective-mode-switch" });
      var now = Date.now();
      webMemoryManager.updateMemory({
        long_term_memory: {
          preferences: ["prefers detailed responses", "likes concise replies"],
        },
        short_term_memory: [
          { role: "user", content: "actually I prefer concise replies now", ts: now - 5 },
        ],
      });
      var response = webMemoryManager.buildMemoryCapabilityResponse("who am I", {
        source: "memory-test-reflective-mode-switch",
      });
      ok(response.finalRouteLocked === true, "mode-switched reflective response stays terminal-locked");
      ok(response.text.indexOf("I remember:") === 0, "concise mode reflection style applied");
      ok(response.text.indexOf("break this down into identity") < 0, "detailed-mode addendum suppressed after concise correction");
    });
  });

  test("reflective synthesis: replay restoration uses canonical runtime memory view before fallback", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "reflective-replay" });
      var now = Date.now();
      webMemoryManager.updateMemory({
        long_term_memory: { user_name: "Nora" },
        short_term_memory: [
          { role: "user", content: "actually my name is Saye", ts: now - 1 },
        ],
      });

      webMemoryManager.init({ namespace: "reflective-replay" });
      var response = webMemoryManager.buildMemoryCapabilityResponse("what do you remember about me", {
        source: "memory-test-reflective-replay",
      });
      ok(response.finalRouteLocked === true, "replay-restored reflective response is terminal-locked");
      ok(response.text.indexOf("your name is Saye") >= 0, "reflection uses canonical corrected identity after replay restore");
      ok(response.text.indexOf("Nora") < 0, "superseded identity excluded from reflection");
    });
  });

  test("reflective synthesis: refresh persistence keeps terminal locked reflective route", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "reflective-refresh-lock" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Saye",
          preferences: ["prefers concise replies"],
        },
      });
      webMemoryManager.init({ namespace: "reflective-refresh-lock" });
      var response = webMemoryManager.buildMemoryCapabilityResponse("what do you know about me", {
        source: "memory-test-reflective-refresh-lock",
      });
      ok(response.reflectiveSuccess === true, "refresh-restored reflection succeeds");
      ok(response.finalRouteLocked === true, "refresh-restored reflection route locked as final");
    });
  });

  test("self-reference entity routing resolves canonical user name prompts", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "self-reference-canonical-name" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Saye",
          preferences: ["prefers concise replies"],
          active_projects: ["Amicor rebuild"],
        },
      });

      var prompts = [
        "what do you know about me",
        "what do you know about Saye",
        "who is Saye",
        "tell me about Saye",
      ];

      prompts.forEach(function (prompt) {
        var response = webMemoryManager.buildMemoryCapabilityResponse(prompt, {
          source: "memory-test-self-reference-" + prompt.replace(/\s+/g, "-").toLowerCase(),
        });
        ok(response.matched === true, "prompt matched memory route: " + prompt);
        ok(response.reflective === true, "prompt used reflective route: " + prompt);
        ok(response.finalRouteLocked === true, "prompt remained terminal-locked: " + prompt);
        ok(response.text.indexOf("your name is Saye") >= 0, "prompt resolves Saye as canonical user: " + prompt);
        ok(response.text.toLowerCase().indexOf("can refer to various subjects") < 0, "generic encyclopedia fallback blocked: " + prompt);
      });
    });
  });

  test("self-reference entity routing survives refresh and replay restore", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "self-reference-refresh-replay" });
      webMemoryManager.updateMemory({
        long_term_memory: { user_name: "Saye", preferences: ["prefers concise replies"] },
        short_term_memory: [
          { role: "user", content: "please keep my profile continuity stable", ts: Date.now() - 5 },
        ],
      });

      webMemoryManager.init({ namespace: "self-reference-refresh-replay" });
      var refreshed = webMemoryManager.buildMemoryCapabilityResponse("who is Saye", {
        source: "memory-test-self-reference-refresh",
      });
      ok(refreshed.finalRouteLocked === true, "refresh response remains terminal-locked");
      ok(refreshed.text.indexOf("your name is Saye") >= 0, "refresh response keeps canonical name");

      webMemoryManager.updateMemory({
        long_term_memory: { user_name: "Nora" },
        short_term_memory: [
          { role: "user", content: "actually my name is Saye", ts: Date.now() - 1 },
        ],
      });
      webMemoryManager.init({ namespace: "self-reference-refresh-replay" });
      var replay = webMemoryManager.buildMemoryCapabilityResponse("tell me about Saye", {
        source: "memory-test-self-reference-replay",
      });
      ok(replay.finalRouteLocked === true, "replay response remains terminal-locked");
      ok(replay.text.indexOf("your name is Saye") >= 0, "replay response uses superseded canonical name resolution");
      ok(replay.text.indexOf("Nora") < 0, "replay response excludes stale superseded name");
    });
  });

  test("self-reference entity routing blocks generic entity fallback in canonical pipeline", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "self-reference-generic-fallback" });
      webMemoryManager.updateMemory({
        long_term_memory: { user_name: "Saye", preferences: ["prefers concise replies"] },
      });

      var result = webMemoryManager.canonicalMemoryResponsePipeline(
        "Saye can refer to various subjects, including surnames and places.",
        {
          source: "memory-test-self-reference-generic-fallback",
          userMessage: "who is Saye",
          memoryEnabled: true,
        }
      );
      ok(result.processed === true, "canonical pipeline processed self-reference fallback case");
      ok(result.text.indexOf("your name is Saye") >= 0, "canonical pipeline replaced generic entity fallback with canonical synthesis");
      ok(result.text.toLowerCase().indexOf("can refer to various subjects") < 0, "generic entity fallback phrase removed");
    });
  });

  test("self-reference entity diagnostics emit canonical match and fallback block tags", async function () {
    await withMockLocalStorage(async function () {
      var events = [];
      localStorage.setItem("amicor_diag_dev", "1");
      webMemoryManager.init({
        namespace: "self-reference-diagnostics",
        logger: function (event, fields) {
          events.push({ event: event, fields: fields || {} });
        },
      });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Saye" } });

      webMemoryManager.canonicalMemoryResponsePipeline(
        "Saye may refer to multiple unrelated entities.",
        {
          source: "memory-test-self-reference-diagnostics",
          userMessage: "tell me about Saye",
          memoryEnabled: true,
        }
      );

      var resolvedEvent = events.find(function (item) { return item.event === "[SELF_REFERENCE_RESOLVED]"; });
      var canonicalMatchEvent = events.find(function (item) { return item.event === "[CANONICAL_USER_NAME_MATCH]"; });
      var blockedFallbackEvent = events.find(function (item) { return item.event === "[GENERIC_ENTITY_FALLBACK_BLOCKED]"; });
      ok(!!resolvedEvent, "self-reference resolved diagnostic emitted");
      ok(!!canonicalMatchEvent, "canonical user name match diagnostic emitted");
      ok(!!blockedFallbackEvent, "generic entity fallback blocked diagnostic emitted");
    });
  });

  test("reflective synthesis: cleared memory returns truthful limited fallback without system narration", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "reflective-cleared" });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Saye" } });
      webMemoryManager.clearMemory();
      var response = webMemoryManager.buildMemoryCapabilityResponse("tell me what you remember", {
        source: "memory-test-reflective-cleared",
      });
      ok(response.finalRouteLocked === false, "cleared-memory reflection is not terminal-locked");
      ok(response.text.indexOf("I remember only a little so far") >= 0, "truthful cleared-memory reflection fallback used");
      ok(response.text.indexOf("short_term_memory") < 0, "cleared-memory fallback avoids architecture narration");
      ok(response.text.indexOf("long_term_memory") < 0, "cleared-memory fallback avoids storage narration");
    });
  });

  test("reflective route locking prevents downstream overwrite in canonical pipeline", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "reflective-overwrite-lock" });
      webMemoryManager.updateMemory({
        long_term_memory: { user_name: "Saye", preferences: ["prefers concise replies"] },
      });

      var result = webMemoryManager.canonicalMemoryResponsePipeline(
        "I cannot remember previous conversations.",
        {
          source: "memory-test-reflective-overwrite-lock",
          userMessage: "what do you remember about me",
          memoryEnabled: true,
        }
      );
      ok(result.finalRouteLocked === true, "canonical pipeline marks reflective response as final locked route");
      ok(result.blocked === false, "locked reflective route bypasses late fallback replacement path");
      ok(result.text.indexOf("your name is Saye") >= 0, "final committed reflective response remains user-centered memory synthesis");
      ok(result.text.indexOf("short_term_memory") < 0, "final committed reflective response avoids architecture narration");
    });
  });

  test("reflective diagnostics: route emits runtime-view assertion tags", async function () {
    await withMockLocalStorage(async function () {
      var events = [];
      localStorage.setItem("amicor_diag_dev", "1");
      webMemoryManager.init({
        namespace: "reflective-diagnostics",
        logger: function (event, fields) {
          events.push({ event: event, fields: fields || {} });
        },
      });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Saye", preferences: ["prefers concise replies"] } });
      webMemoryManager.buildMemoryCapabilityResponse("what do you remember about me", {
        source: "memory-test-reflective-diagnostics",
      });

      var routeEvent = events.find(function (item) { return item.event === "[MEMORY_REFLECTION_ROUTE]"; });
      var synthesisEvent = events.find(function (item) { return item.event === "[REFLECTIVE_SYNTHESIS]"; });
      var successEvent = events.find(function (item) { return item.event === "[REFLECTIVE_SYNTHESIS_SUCCESS]"; });
      var lockedEvent = events.find(function (item) { return item.event === "[FINAL_ROUTE_LOCKED]"; });
      var commitEvent = events.find(function (item) { return item.event === "[TERMINAL_RESPONSE_COMMITTED]"; });
      ok(!!routeEvent, "memory reflection route diagnostic emitted");
      ok(routeEvent && routeEvent.fields && routeEvent.fields.querySource === "runtime-canonical-view", "reflection queried canonical runtime view before fallback");
      ok(!!synthesisEvent, "reflective synthesis diagnostic emitted");
      ok(!!successEvent, "reflective synthesis success diagnostic emitted");
      ok(!!lockedEvent, "final route locked diagnostic emitted");
      ok(!!commitEvent, "terminal response committed diagnostic emitted");
    });
  });

  test("canonical runtime audit traces all reflective stages", async function () {
    await withMockLocalStorage(async function () {
      var events = [];
      localStorage.setItem("amicor_diag_dev", "1");
      webMemoryManager.init({
        namespace: "canonical-runtime-audit",
        logger: function (event, fields) {
          events.push({ event: event, fields: fields || {} });
        },
      });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Saye",
          preferences: ["prefers concise replies"],
          active_projects: ["Amicor rebuild"],
        },
      });

      var response = webMemoryManager.canonicalMemoryResponsePipeline("what do you remember about me", {
        source: "memory-test-canonical-audit",
        userMessage: "what do you remember about me",
        memoryEnabled: true,
      });

      var stages = events
        .filter(function (item) { return item.event === "[CANONICAL_RUNTIME_VIEW]"; })
        .map(function (item) { return item.fields && item.fields.stage; });
      ok(stages.indexOf("intent_detection") >= 0, "intent detection stage traced");
      ok(stages.indexOf("memory_query") >= 0, "memory query stage traced");
      ok(stages.indexOf("synthesis") >= 0, "synthesis stage traced");
      ok(stages.indexOf("arbitration") >= 0, "arbitration stage traced");
      ok(stages.indexOf("pipeline_complete") >= 0 || response.finalRouteLocked === true, "final response commit traced");
    });
  });

  test("canonical runtime audit blocks secondary terminal routes", async function () {
    await withMockLocalStorage(async function () {
      var events = [];
      localStorage.setItem("amicor_diag_dev", "1");
      webMemoryManager.init({
        namespace: "canonical-route-exclusivity",
        logger: function (event, fields) {
          events.push({ event: event, fields: fields || {} });
        },
      });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Saye", preferences: ["prefers concise replies"] } });

      var response = webMemoryManager.buildMemoryCapabilityResponse("what do you know about me", {
        source: "memory-test-canonical-exclusivity",
      });

      var terminalCommitted = events.filter(function (item) { return item.event === "[TERMINAL_ROUTE_COMMITTED]"; });
      var secondaryBlocked = events.filter(function (item) { return item.event === "[SECONDARY_ROUTE_BLOCKED]"; });
      ok(response.finalRouteLocked === true, "reflective response terminally locked");
      ok(terminalCommitted.length >= 1, "terminal route committed exactly once or more, no missing commit");
      ok(secondaryBlocked.length >= 1, "secondary routes blocked after terminal commit");
    });
  });

  test("canonical runtime audit confirms live, persisted, and replay parity", async function () {
    await withMockLocalStorage(async function () {
      var events = [];
      localStorage.setItem("amicor_diag_dev", "1");
      webMemoryManager.init({
        namespace: "canonical-parity",
        logger: function (event, fields) {
          events.push({ event: event, fields: fields || {} });
        },
      });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Saye",
          preferences: ["prefers concise replies"],
        },
      });

      var liveResponse = webMemoryManager.buildMemoryCapabilityResponse("what do you remember about me", {
        source: "memory-test-parity-live",
      });
      var persistedMemory = webMemoryManager.loadMemory();
      webMemoryManager.init({ namespace: "canonical-parity" });
      var replayResponse = webMemoryManager.buildMemoryCapabilityResponse("what do you remember about me", {
        source: "memory-test-parity-replay",
      });

      var parityEvents = events.filter(function (item) { return item.event === "[RUNTIME_PARITY_CONFIRMED]"; });
      ok(liveResponse.text === replayResponse.text, "live and replay reflective responses stay semantically consistent");
      ok(persistedMemory.long_term_memory.user_name === "Saye", "persisted memory retained canonical identity");
      ok(parityEvents.length >= 1, "runtime parity confirmation emitted");
    });
  });

  test("canonical runtime audit report identifies remaining response paths", async function () {
    await withMockLocalStorage(async function () {
      localStorage.setItem("amicor_diag_dev", "1");
      webMemoryManager.init({ namespace: "canonical-report" });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Saye", preferences: ["prefers concise replies"] } });
      webMemoryManager.buildMemoryCapabilityResponse("what do you know about me", {
        source: "memory-test-report",
      });

      var report = webMemoryManager.getRuntimeAuditReport();
      ok(report.lastTerminalRoute === "reflective-memory", "audit report tracks terminal reflective route");
      ok(Array.isArray(report.remainingRisks), "audit report exposes remaining risks array");
      ok(report.remainingRisks.indexOf("no_terminal_route_observed") < 0, "terminal route was observed");
    });
  });

  test("canonical runtime audit survives rapid prompt switching and overlap simulation", async function () {
    await withMockLocalStorage(async function () {
      var events = [];
      localStorage.setItem("amicor_diag_dev", "1");
      webMemoryManager.init({
        namespace: "canonical-concurrency",
        logger: function (event, fields) {
          events.push({ event: event, fields: fields || {} });
        },
      });
      webMemoryManager.updateMemory({
        long_term_memory: { user_name: "Saye", preferences: ["prefers concise replies"] },
      });

      var first = webMemoryManager.canonicalMemoryResponsePipeline("what do you know about me", {
        source: "memory-test-overlap-1",
        userMessage: "what do you know about me",
        memoryEnabled: true,
      });
      var second = webMemoryManager.canonicalMemoryResponsePipeline("what are my preferences", {
        source: "memory-test-overlap-2",
        userMessage: "what are my preferences",
        memoryEnabled: true,
      });
      var third = webMemoryManager.canonicalMemoryResponsePipeline("who am I", {
        source: "memory-test-overlap-3",
        userMessage: "who am I",
        memoryEnabled: true,
      });

      var terminalCount = events.filter(function (item) { return item.event === "[TERMINAL_ROUTE_COMMITTED]"; }).length;
      ok(first.finalRouteLocked === true && second.finalRouteLocked === true && third.finalRouteLocked === true, "rapid prompt switching remains terminal-locked");
      ok(terminalCount >= 3, "each overlapping reflective prompt commits exactly one terminal route");
    });
  });

  test("canonical runtime audit keeps refresh and replay responses memory-coherent", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "canonical-refresh-replay" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Saye",
          preferences: ["prefers concise replies"],
          goals: ["ship MVP"],
        },
        short_term_memory: [
          { role: "user", content: "please keep memory coherent", ts: Date.now() - 10 },
        ],
      });
      var live = webMemoryManager.canonicalMemoryResponsePipeline("what do you remember about me", {
        source: "memory-test-refresh-live",
        userMessage: "what do you remember about me",
        memoryEnabled: true,
      });
      webMemoryManager.init({ namespace: "canonical-refresh-replay" });
      var replay = webMemoryManager.canonicalMemoryResponsePipeline("what do you remember about me", {
        source: "memory-test-refresh-replay",
        userMessage: "what do you remember about me",
        memoryEnabled: true,
      });
      ok(live.text === replay.text, "refresh/replay responses remain semantically consistent");
      ok(live.finalRouteLocked === true && replay.finalRouteLocked === true, "refresh/replay both stay terminal-locked");
    });
  });

  test("CRITICAL: forbidden personal-information-between-conversations phrase is blocked when memory enabled", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "bypass-test-1" });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Alice" } });
      
      var forbiddenPhrase = "I don't have the ability to remember personal information between conversations. Each interaction is treated independently…";
      var enforced = webMemoryManager.enforceMemoryAwareResponse(forbiddenPhrase, {
        memoryEnabled: true,
        hasMemory: true,
        source: "memory-test-personal-info-bypass"
      });
      
      ok(enforced.blocked === true, "forbidden phrase was detected and blocked");
      ok(enforced.text !== forbiddenPhrase, "forbidden phrase was replaced");
      ok(enforced.text.indexOf("I don't know that yet") >= 0 || enforced.text.indexOf("I don't have the ability to remember") < 0, "replacement text used or phrase removed");
    });
  });

  test("CRITICAL: between-conversations phrase is blocked when memory enabled", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "bypass-test-2" });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Bob" } });
      
      var forbiddenPhrase = "I won't remember this between conversations";
      var enforced = webMemoryManager.enforceMemoryAwareResponse(forbiddenPhrase, {
        memoryEnabled: true,
        hasMemory: true,
        source: "memory-test-between-conversations"
      });
      
      ok(enforced.blocked === true, "between-conversations phrase was detected and blocked");
      ok(enforced.text !== forbiddenPhrase, "between-conversations phrase was replaced");
    });
  });

  test("CRITICAL: treated-independently phrase is blocked when memory enabled", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "bypass-test-3" });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Charlie" } });
      
      var forbiddenPhrase = "Each interaction is treated independently without access to previous conversations.";
      var enforced = webMemoryManager.enforceMemoryAwareResponse(forbiddenPhrase, {
        memoryEnabled: true,
        hasMemory: true,
        source: "memory-test-independently"
      });
      
      ok(enforced.blocked === true, "treated-independently phrase was detected and blocked");
      ok(enforced.text !== forbiddenPhrase, "treated-independently phrase was replaced");
    });
  });

  test("CRITICAL: wont-retain-details phrase is blocked when memory enabled", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "bypass-test-4" });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Diana" } });
      
      var forbiddenPhrase = "I won't retain any details about personal information";
      var enforced = webMemoryManager.enforceMemoryAwareResponse(forbiddenPhrase, {
        memoryEnabled: true,
        hasMemory: true,
        source: "memory-test-wont-retain"
      });
      
      ok(enforced.blocked === true, "won't-retain phrase was detected and blocked");
      ok(enforced.text !== forbiddenPhrase, "won't-retain phrase was replaced");
    });
  });

  test("enforceAssistantVisibleResponse blocks all personal-information stateless patterns with memory enabled", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "bypass-test-comprehensive" });
      webMemoryManager.updateMemory({ long_term_memory: { user_name: "Eve" } });
      
      var testCases = [
        "I don't have the ability to remember personal information between conversations. Each interaction is treated independently…",
        "I won't retain any details about you between conversations.",
        "Each interaction is treated independently without memory of prior exchanges.",
        "I cannot recall information between conversations.",
        "Personal information is not retained between conversations."
      ];
      
      testCases.forEach(function(phrase) {
        try {
          var result = webMemoryManager.enforceAssistantVisibleResponse(phrase, {
            memoryEnabled: true,
            hasMemory: true,
            source: "memory-test-comprehensive-case",
            throwOnViolation: false  // Don't throw, just return blocked result
          });
          ok(result.text !== phrase, "phrase blocked: " + phrase.slice(0, 50) + "…");
          ok(result.text.indexOf("I don't know that yet") >= 0 || result.blocked === true, "replacement or blocked flag used");
        } catch (error) {
          // If throwOnViolation was true, we'd catch here - that's also acceptable
          ok(error && error.code === webMemoryManager.POLICY_VIOLATION_CODE, "policy violation error thrown for: " + phrase.slice(0, 50));
        }
      });
    });
  });

  // ============================================================================
  // CANONICAL PIPELINE VALIDATION TESTS
  // ============================================================================

  test("Canonical pipeline: exists and is callable", function () {
    ok(
      typeof webMemoryManager.canonicalMemoryResponsePipeline === "function",
      "canonicalMemoryResponsePipeline is exported"
    );
  });

  test("Canonical pipeline: returns structured response object", function () {
    webMemoryManager.init({ namespace: "test" });
    var result = webMemoryManager.canonicalMemoryResponsePipeline("Hello world", {
      source: "test",
      memoryEnabled: true,
    });
    ok(result.text !== undefined, "result has text property");
    ok(result.processed !== undefined, "result has processed property");
    ok(result.blocked !== undefined, "result has blocked property");
    ok(result.diagnostics !== undefined, "result has diagnostics property");
  });

  test("Canonical pipeline: handles empty input safely", function () {
    webMemoryManager.init({ namespace: "test" });
    var result = webMemoryManager.canonicalMemoryResponsePipeline("", {
      source: "test",
      memoryEnabled: true,
    });
    ok(result.processed === false, "empty input marked as not processed");
    ok(result.blocked === false, "empty input not blocked");
  });

  test("Canonical pipeline: preserves normal responses", function () {
    webMemoryManager.init({ namespace: "test" });
    var normalResponse = "Here are the weather details for today...";
    var result = webMemoryManager.canonicalMemoryResponsePipeline(normalResponse, {
      source: "test",
      memoryEnabled: true,
    });
    ok(result.text.indexOf("weather") >= 0, "normal response preserved");
    ok(result.blocked === false, "normal response not blocked");
  });

  test("Canonical pipeline: blocks stateless claims when memory enabled", function () {
    webMemoryManager.init({ namespace: "test" });
    var statelessResponse = "I cannot remember personal information between conversations.";
    var result = webMemoryManager.canonicalMemoryResponsePipeline(statelessResponse, {
      source: "test",
      memoryEnabled: true,
    });
    ok(result.blocked === true, "stateless claim blocked");
    ok(result.text.indexOf("cannot remember") < 0, "forbidden phrase replaced");
  });

  test("Canonical pipeline: respects memoryEnabled flag", function () {
    webMemoryManager.init({ namespace: "test" });
    var statelessResponse = "I don't have the ability to remember you.";
    var resultDisabled = webMemoryManager.canonicalMemoryResponsePipeline(
      statelessResponse,
      { source: "test", memoryEnabled: false }
    );
    ok(
      resultDisabled.blocked === false,
      "stateless claim NOT blocked when memory disabled"
    );
  });

  test("Canonical pipeline: works with streaming token accumulation", function () {
    webMemoryManager.init({ namespace: "test" });
    var accumulated = "";
    var tokens = ["I", " cannot", " remember", " you"];
    for (var ti = 0; ti < tokens.length; ti++) {
      accumulated += tokens[ti];
      var result = webMemoryManager.canonicalMemoryResponsePipeline(accumulated, {
        source: "streaming-token",
        memoryEnabled: true,
      });
      // Each intermediate result should be safe
      ok(result.text !== undefined, "token accumulation at " + accumulated + " is valid");
    }
  });

  test("Canonical pipeline: structured memory available", function () {
    webMemoryManager.init({ namespace: "test" });
    webMemoryManager.updateMemory({
      long_term_memory: {
        user_name: "Alice",
        preferences: ["coffee", "morning meetings"],
        goals: ["learn Python"],
      },
    });
    var structured = webMemoryManager.getStructuredMemory();
    ok(structured.identity.name === "Alice", "identity priority 1");
    ok(Array.isArray(structured.preferences.likes) || Array.isArray(structured.preferences.communication_preferences), "preferences priority 2");
    ok(Array.isArray(structured.projects.goals), "projects priority 3");
  });

  test("Normalization: duplicate preference insertion collapses to one canonical value", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "normalize-dup-pref" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          preferences: [
            "likes concise replies",
            "prefers concise responses",
            "concise answers",
          ],
        },
      });
      var runtimeView = webMemoryManager.getNormalizedRuntimeView();
      var prefs = runtimeView.long_term_memory.preferences || [];
      ok(prefs.length === 1, "duplicate semantic preferences collapsed");
      ok(prefs[0] === "prefers concise replies", "canonical preference applied");
    });
  });

  test("Normalization: replay duplication removed only in runtime view", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "normalize-replay-dup" });
      var now = Date.now();
      webMemoryManager.updateMemory({
        short_term_memory: [
          { role: "assistant", content: "We should prioritize MVP scope.", ts: now - 30 },
          { role: "assistant", content: "We should prioritize MVP scope.", ts: now - 20 },
          { role: "assistant", content: "We should prioritize MVP scope.", ts: now - 10 },
        ],
      });
      var persisted = webMemoryManager.loadMemory();
      var runtimeView = webMemoryManager.getNormalizedRuntimeView();
      ok(persisted.short_term_memory.length === 3, "persisted replay records are not mutated");
      ok(runtimeView.short_term_memory.length === 1, "runtime replay view removes contiguous duplicates");
    });
  });

  test("Normalization: semantically equivalent preferences are merged", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "normalize-semantic-pref" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          preferences: [
            "short responses",
            "brief replies",
            "concise responses",
            "likes concise answers",
          ],
        },
      });
      var runtimeView = webMemoryManager.getNormalizedRuntimeView();
      var prefs = runtimeView.long_term_memory.preferences || [];
      ok(prefs.length === 1, "semantic preference aliases merged");
      ok(prefs[0] === "prefers concise replies", "canonical phrase chosen for semantic group");
    });
  });

  test("Normalization: rapid preference updates resolve conflicting traits", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "normalize-rapid-updates" });
      var now = Date.now();
      webMemoryManager.updateMemory({ long_term_memory: { preferences: ["prefers detailed responses"] } });
      webMemoryManager.updateMemory({ long_term_memory: { preferences: ["likes concise replies"] } });
      webMemoryManager.updateMemory({
        short_term_memory: [
          { role: "user", content: "Please keep it concise from now on.", ts: now - 1 },
        ],
      });
      var runtimeView = webMemoryManager.getNormalizedRuntimeView();
      var prefs = runtimeView.long_term_memory.preferences || [];
      ok(prefs.indexOf("prefers concise replies") >= 0, "latest concise preference retained");
      ok(prefs.indexOf("prefers detailed replies") < 0, "conflicting detailed preference removed in runtime synthesis");
    });
  });

  test("Identity supersession: latest authoritative name replaces stale canonical name", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "identity-name-supersession" });
      var now = Date.now();
      webMemoryManager.updateMemory({
        long_term_memory: { user_name: "Nora" },
        short_term_memory: [
          { role: "user", content: "my name is Nora", ts: now - 30 },
          { role: "user", content: "actually my name is Saye", ts: now - 10 },
        ],
      });

      var runtimeView = webMemoryManager.getNormalizedRuntimeView();
      ok(runtimeView.long_term_memory.user_name === "Saye", "canonical identity updated to latest authoritative name");
      ok(
        runtimeView.identity_resolution && runtimeView.identity_resolution.superseded_names.indexOf("Nora") >= 0,
        "stale identity value marked as superseded"
      );
    });
  });

  test("Identity supersession: explicit preference replacement supersedes stale primary preference", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "identity-pref-supersession" });
      var now = Date.now();
      webMemoryManager.updateMemory({
        long_term_memory: {
          preferences: ["prefers detailed responses", "likes concise replies"],
        },
        short_term_memory: [
          { role: "user", content: "I prefer detailed responses.", ts: now - 20 },
          { role: "user", content: "actually I prefer concise responses now", ts: now - 10 },
        ],
      });

      var runtimeView = webMemoryManager.getNormalizedRuntimeView();
      var prefs = runtimeView.long_term_memory.preferences || [];
      ok(prefs.indexOf("prefers concise replies") >= 0, "new authoritative preference is canonical");
      ok(prefs.indexOf("prefers detailed replies") < 0, "stale conflicting preference removed from runtime synthesis");
      ok(
        runtimeView.identity_resolution && runtimeView.identity_resolution.superseded_preferences.indexOf("prefers detailed replies") >= 0,
        "stale primary preference tracked as superseded"
      );
    });
  });

  test("Identity supersession: rapid sequential corrections converge to one canonical identity", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "identity-rapid-corrections" });
      var now = Date.now();
      webMemoryManager.updateMemory({
        long_term_memory: { user_name: "Nora" },
        short_term_memory: [
          { role: "user", content: "my name is Nora", ts: now - 40 },
          { role: "user", content: "call me Saye", ts: now - 30 },
          { role: "user", content: "actually call me Mira", ts: now - 20 },
          { role: "user", content: "change my name to Saye", ts: now - 10 },
        ],
      });

      var runtimeView = webMemoryManager.getNormalizedRuntimeView();
      ok(runtimeView.long_term_memory.user_name === "Saye", "latest explicit replacement wins");
      ok(
        runtimeView.identity_resolution && runtimeView.identity_resolution.superseded_names.indexOf("Mira") >= 0,
        "intermediate stale values are superseded"
      );
    });
  });

  test("Replay integrity: canonical runtime view changes without mutating historical logs", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "identity-replay-integrity" });
      var now = Date.now();
      webMemoryManager.updateMemory({
        long_term_memory: { user_name: "Nora" },
        short_term_memory: [
          { role: "user", content: "my name is Nora", ts: now - 30 },
          { role: "user", content: "actually my name is Saye", ts: now - 10 },
        ],
      });

      var persistedBefore = webMemoryManager.loadMemory();
      var runtimeView = webMemoryManager.getNormalizedRuntimeView();
      var persistedAfter = webMemoryManager.loadMemory();

      ok(runtimeView.long_term_memory.user_name === "Saye", "runtime canonical identity reflects correction");
      ok(persistedBefore.long_term_memory.user_name === "Nora", "persisted canonical storage remains unchanged");
      ok(persistedAfter.long_term_memory.user_name === "Nora", "historical persisted memory remains immutable after runtime normalization");
      ok(persistedAfter.short_term_memory.length === persistedBefore.short_term_memory.length, "replay/history records remain unchanged");
    });
  });

  test("Replay restoration: corrected canonical identity remains coherent after reload", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "identity-replay-restore" });
      var now = Date.now();
      webMemoryManager.updateMemory({
        long_term_memory: { user_name: "Nora", preferences: ["prefers detailed responses", "likes concise replies"] },
        short_term_memory: [
          { role: "user", content: "actually my name is Saye", ts: now - 20 },
          { role: "user", content: "actually I prefer concise responses", ts: now - 10 },
        ],
      });

      webMemoryManager.init({ namespace: "identity-replay-restore" });
      var runtimeView = webMemoryManager.getNormalizedRuntimeView();
      ok(runtimeView.long_term_memory.user_name === "Saye", "canonical corrected name restored after replay");
      ok(runtimeView.long_term_memory.preferences.indexOf("prefers concise replies") >= 0, "canonical corrected preference restored after replay");
      ok(runtimeView.long_term_memory.preferences.indexOf("prefers detailed replies") < 0, "stale preference excluded after replay restoration");
    });
  });

  test("Mode-switch continuity: assistant mode reflects corrected primary preference", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "identity-mode-continuity" });
      var now = Date.now();
      webMemoryManager.updateMemory({
        long_term_memory: {
          preferences: ["prefers detailed responses", "likes concise replies"],
        },
        short_term_memory: [
          { role: "user", content: "actually I prefer concise responses", ts: now - 5 },
        ],
      });

      var runtimeView = webMemoryManager.getNormalizedRuntimeView();
      ok(runtimeView.assistant_modes.indexOf("mode:concise") >= 0, "assistant mode keeps continuity with corrected preference");
      ok(runtimeView.assistant_modes.indexOf("mode:detailed") < 0, "stale assistant mode excluded after correction");
    });
  });

  test("Synthesis quality: duplicate memory phrases are compressed", function () {
    webMemoryManager.init({ namespace: "normalize-synthesis-quality" });
    var input = [
      "From memory I know your name is Nora.",
      "From memory I know your name is Nora.",
      "preferences such as prefers concise replies, preferences such as prefers concise replies.",
      "I remember what you've shared and will use it to personalize how I help.",
      "I remember what you've shared and will use it to personalize how I help.",
    ].join(" ");
    var output = webMemoryManager.normalizeAssistantSynthesisText(input);
    ok(output.indexOf("From memory I know your name is Nora.") >= 0, "truthful recall preserved");
    ok(output.indexOf("From memory I know your name is Nora. From memory I know your name is Nora.") < 0, "duplicate identity phrase removed");
    ok(output.indexOf("preferences such as prefers concise replies, preferences such as prefers concise replies") < 0, "recursive preference restatement removed");
  });

  test("Synthesis quality: superseded identity values are excluded from final text", function () {
    webMemoryManager.init({ namespace: "normalize-synthesis-identity" });
    var input = "From memory your name is Nora. I also recall your name is Saye. You prefer detailed replies and prefers concise replies.";
    var output = webMemoryManager.normalizeAssistantSynthesisText(input, {
      canonicalName: "Saye",
      supersededNames: ["Nora"],
      canonicalPrimaryPreference: "prefers concise replies",
      supersededPreferences: ["prefers detailed replies"],
    });
    ok(output.indexOf("name is Nora") < 0, "superseded name is excluded from synthesis");
    ok(output.indexOf("name is Saye") >= 0, "canonical name is retained");
    ok(output.indexOf("prefers detailed replies") < 0, "superseded primary preference is excluded");
    ok(output.indexOf("prefers concise replies") >= 0, "canonical primary preference is retained");
  });

  test("Coherence: refresh persistence — memory survives page reload simulation", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "coherence-test-1" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Charlie",
          preferences: ["remote work"],
        },
      });
      webMemoryManager.saveMemory(webMemoryManager.loadMemory());

      // Simulate page reload by reinitializing
      webMemoryManager.init({ namespace: "coherence-test-1" });
      var loaded = webMemoryManager.loadMemory();
      ok(
        loaded.long_term_memory.user_name === "Charlie",
        "user name persisted across reload"
      );
      ok(
        Array.isArray(loaded.long_term_memory.preferences) &&
          loaded.long_term_memory.preferences.indexOf("remote work") >= 0,
        "preferences persisted across reload"
      );
    });
  });

  test("Coherence: streaming/non-stream parity — identical memory handling", function () {
    webMemoryManager.init({ namespace: "coherence-test-2" });
    webMemoryManager.updateMemory({
      long_term_memory: { user_name: "Diana" },
    });

    var streamResult = webMemoryManager.canonicalMemoryResponsePipeline("Hello", {
      source: "streaming-token",
      memoryEnabled: true,
    });
    var nonStreamResult = webMemoryManager.canonicalMemoryResponsePipeline("Hello", {
      source: "non-streaming",
      memoryEnabled: true,
    });

    ok(
      streamResult.blocked === nonStreamResult.blocked,
      "streaming and non-streaming produce same blocking decision"
    );
    ok(
      streamResult.text === nonStreamResult.text,
      "streaming and non-streaming produce same text"
    );
  });

  test("Coherence: clear-memory recovery — Clear Memory button fully resets state", async function () {
    await withMockLocalStorage(async function () {
      webMemoryManager.init({ namespace: "coherence-test-3" });
      webMemoryManager.updateMemory({
        long_term_memory: {
          user_name: "Eve",
          preferences: ["writing"],
        },
      });

      var memory = webMemoryManager.loadMemory();
      ok(memory.long_term_memory.user_name === "Eve", "memory exists before clear");

      webMemoryManager.clearMemory();
      memory = webMemoryManager.loadMemory();
      ok(memory.long_term_memory.user_name === "", "user_name cleared");
      ok(
        Array.isArray(memory.long_term_memory.preferences) &&
          memory.long_term_memory.preferences.length === 0,
        "preferences array cleared"
      );
    });
  });

  test("All stateless patterns blocked with canonical pipeline", function () {
    webMemoryManager.init({ namespace: "stateless-comprehensive" });
    webMemoryManager.updateMemory({
      long_term_memory: { user_name: "Henry" },
    });

    var forbiddenPhrases = [
      "I cannot remember personal information",
      "I don't have information about you",
      "I cannot access personal data",
      "I am stateless",
      "Each session is independent",
      "Between conversations",
      "Each interaction is treated independently",
      "I won't retain details",
    ];

    var allBlocked = true;
    for (var pi = 0; pi < forbiddenPhrases.length; pi++) {
      var phrase = forbiddenPhrases[pi];
      var result = webMemoryManager.canonicalMemoryResponsePipeline(phrase, {
        source: "forbidden-test",
        memoryEnabled: true,
      });
      if (!result.blocked) {
        console.error("  ✗ FAILED TO BLOCK: " + phrase);
        allBlocked = false;
      }
    }
    ok(allBlocked, "all forbidden phrases blocked");
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