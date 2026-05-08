/**
 * orchestrator.test.js — AmiCorOrchestrator Test Suite
 *
 * Run from browser console (after loading orchestrator.js):
 *   orchestratorTests()
 *   orchestratorTests("retry")   ← filter groups by name
 *
 * Requires: render.js, streaming.js, orchestrator.js
 */

(function (global) {
  "use strict";

  // ─────────────────────────────────────────────────────────────────────────
  // Mock helpers
  // ─────────────────────────────────────────────────────────────────────────

  /** Minimal mock DOM element that records innerHTML assignments. */
  function mockEl() {
    var _html = "";
    var _patches = 0;
    return {
      get innerHTML()   { return _html; },
      set innerHTML(v)  { _html = v; _patches++; },
      querySelector()   { return null; },
      _patchCount()     { return _patches; },
    };
  }

  /** Collect all events emitted on a conversation into an array. */
  function captureEvents(conv) {
    var log = [];
    var evts = ["onMessageStart","onChunk","onRender","onComplete","onCancel","onError","onRetry"];
    evts.forEach(function (e) {
      conv.on(e, function (payload) { log.push({ event: e, payload: payload }); });
    });
    return log;
  }

  /** Create a fresh conversation with a unique id. */
  function makeConv(opts) {
    return global.AmiCorOrchestrator.createConversation(
      Object.assign({ id: "test-conv-" + Date.now() + "-" + Math.random() }, opts || {})
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Assertion helpers
  // ─────────────────────────────────────────────────────────────────────────

  function ok(cond, desc) {
    return { ok: !!cond, desc: desc };
  }

  function eq(a, b, desc) {
    return {
      ok: a === b,
      desc: desc,
      detail: a !== b ? ("expected " + JSON.stringify(b) + " got " + JSON.stringify(a)) : undefined,
    };
  }

  function gt(a, b, desc) {
    return {
      ok: a > b,
      desc: desc,
      detail: !(a > b) ? (String(a) + " is not > " + String(b)) : undefined,
    };
  }

  function contains(str, sub, desc) {
    return {
      ok: typeof str === "string" && str.indexOf(sub) !== -1,
      desc: desc,
      detail: (typeof str !== "string" || str.indexOf(sub) === -1)
        ? ('"' + sub + '" not found in: ' + String(str).slice(0,120))
        : undefined,
    };
  }

  function lacks(str, sub, desc) {
    return {
      ok: typeof str !== "string" || str.indexOf(sub) === -1,
      desc: desc,
      detail: (typeof str === "string" && str.indexOf(sub) !== -1)
        ? ('"' + sub + '" found in: ' + String(str).slice(0,120))
        : undefined,
    };
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Test groups (30+ tests)
  // ─────────────────────────────────────────────────────────────────────────

  var groups = [

    // ── Conversation lifecycle ─────────────────────────────────────────────
    {
      name: "conv-create-destroy",
      run: function () {
        var conv = makeConv({ id: "cd-test" });
        var id   = conv.id;
        AmiCorOrchestrator.destroyConversation(id);
        return [
          ok(AmiCorOrchestrator.getConversation(id) === undefined, "conversation removed after destroyConversation"),
        ];
      },
    },

    {
      name: "conv-reset-clears-history",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("hello"); sess.finish();
        conv.reset();
        return [
          eq(conv.getHistory().length, 0, "history empty after reset"),
          eq(conv.getStats().totalMessages, 0, "stats reset"),
        ];
      },
    },

    {
      name: "conv-list-conversations",
      run: function () {
        var id  = "list-test-" + Date.now();
        var conv = AmiCorOrchestrator.createConversation({ id: id });
        var list = AmiCorOrchestrator.listConversations();
        AmiCorOrchestrator.destroyConversation(id);
        return [
          ok(list.indexOf(id) !== -1, "id appears in listConversations()"),
        ];
      },
    },

    // ── Message lifecycle ─────────────────────────────────────────────────
    {
      name: "message-state-completed",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("Hello world");
        sess.finish();
        var hist = conv.getHistory();
        return [
          eq(hist.length, 1, "one message in history"),
          eq(hist[0].streamingState, "completed", "state = completed"),
          ok(hist[0].timestamps.completed !== null, "completed timestamp set"),
        ];
      },
    },

    {
      name: "message-role-preserved",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ role: "assistant", element: mockEl() });
        sess.push("text"); sess.finish();
        return eq(conv.getHistory()[0].role, "assistant", "role = assistant");
      },
    },

    {
      name: "message-token-count",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("a"); sess.push("b"); sess.push("c"); sess.finish();
        return eq(conv.getHistory()[0].tokenCount, 3, "tokenCount = 3 after 3 push() calls");
      },
    },

    {
      name: "message-raw-text-accumulates",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("Hello "); sess.push("world"); sess.finish();
        return eq(conv.getHistory()[0].rawText, "Hello world", "rawText accumulated correctly");
      },
    },

    {
      name: "message-snapshot-is-frozen",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("test"); sess.finish();
        var snap = conv.getHistory()[0];
        var threw = false;
        try { snap.rawText = "mutated"; } catch (e) { threw = true; }
        return ok(threw || snap.rawText !== "mutated", "snapshot is immutable");
      },
    },

    // ── Event ordering ────────────────────────────────────────────────────
    {
      name: "events-order-start-chunk-complete",
      run: function () {
        var conv = makeConv();
        var log  = captureEvents(conv);
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("hello"); sess.finish();
        var eventNames = log.map(function (e) { return e.event; });
        return [
          eq(eventNames[0], "onMessageStart", "first event = onMessageStart"),
          ok(eventNames.indexOf("onChunk") !== -1, "onChunk fired"),
          eq(eventNames[eventNames.length - 1], "onComplete", "last event = onComplete"),
        ];
      },
    },

    {
      name: "events-onChunk-payload",
      run: function () {
        var conv   = makeConv();
        var chunks = [];
        conv.on("onChunk", function (p) { chunks.push(p.chunk); });
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("a"); sess.push("b"); sess.finish();
        return [
          eq(chunks[0], "a", "first chunk = 'a'"),
          eq(chunks[1], "b", "second chunk = 'b'"),
        ];
      },
    },

    {
      name: "events-onComplete-includes-snapshot",
      run: function () {
        var conv = makeConv();
        var completed = null;
        conv.on("onComplete", function (p) { completed = p; });
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("done"); sess.finish();
        return [
          ok(completed !== null, "onComplete fired"),
          ok(completed.message !== null, "onComplete payload has message snapshot"),
          eq(completed.message.streamingState, "completed", "snapshot state = completed"),
        ];
      },
    },

    {
      name: "events-onCancel-fired",
      run: function () {
        var conv      = makeConv();
        var cancelled = null;
        conv.on("onCancel", function (p) { cancelled = p; });
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("partial"); sess.cancel();
        return [
          ok(cancelled !== null, "onCancel fired"),
          eq(cancelled.message.streamingState, "cancelled", "state = cancelled"),
        ];
      },
    },

    {
      name: "events-onError-fired-on-markFailed",
      run: function () {
        var conv   = makeConv();
        var errors = [];
        conv.on("onError", function (p) { errors.push(p); });
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("some text");
        conv.markFailed(sess._message.id, new Error("network timeout"));
        return [
          ok(errors.length > 0, "onError fired"),
          ok(errors[0].error instanceof Error, "error payload is Error object"),
        ];
      },
    },

    // ── Cancellation ──────────────────────────────────────────────────────
    {
      name: "cancel-mid-stream",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("partial tex");
        sess.cancel();
        // Further pushes after cancel are no-ops
        sess.push("should be ignored");
        return [
          eq(conv.getHistory()[0].streamingState, "cancelled", "state = cancelled"),
          lacks(conv.getHistory()[0].rawText, "should be ignored", "push after cancel ignored"),
        ];
      },
    },

    {
      name: "cancel-preserves-partial-text",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("partial ");
        sess.push("content");
        sess.cancel();
        return [
          contains(conv.getHistory()[0].rawText, "partial content", "partial text preserved after cancel"),
        ];
      },
    },

    {
      name: "cancel-active-via-conversation",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("streaming...");
        conv.cancelActive();
        return [
          eq(conv.getHistory()[0].streamingState, "cancelled", "cancelActive() cancels current session"),
        ];
      },
    },

    {
      name: "cancel-abort-signal-available",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        var signal = sess.getAbortSignal();
        // AbortController may not be available in all envs
        if (signal === null) {
          return ok(true, "AbortController not available (skipped)");
        }
        sess.cancel();
        return ok(signal.aborted, "AbortSignal.aborted = true after cancel()");
      },
    },

    // ── Retry ──────────────────────────────────────────────────────────────
    {
      name: "retry-increments-count",
      run: function () {
        var conv = makeConv({ retryMax: 3 });
        var sess = conv.startMessage({ element: mockEl() });
        var mid  = sess._message.id;
        sess.push("text"); sess.cancel();

        conv.retry(mid, mockEl());
        conv.cancelActive();

        return [
          eq(conv.getHistory()[0].retryCount, 1, "retryCount = 1 after one retry"),
          eq(conv.getStats().totalRetries, 1, "totalRetries stat = 1"),
        ];
      },
    },

    {
      name: "retry-fires-onRetry-event",
      run: function () {
        var conv    = makeConv({ retryMax: 3 });
        var retried = null;
        conv.on("onRetry", function (p) { retried = p; });
        var sess = conv.startMessage({ element: mockEl() });
        var mid  = sess._message.id;
        sess.cancel();
        conv.retry(mid, mockEl());
        conv.cancelActive();
        return [
          ok(retried !== null, "onRetry event fired"),
          eq(retried.retryCount, 1, "retryCount in payload = 1"),
        ];
      },
    },

    {
      name: "retry-resets-rawText",
      run: function () {
        var conv = makeConv({ retryMax: 3 });
        var sess = conv.startMessage({ element: mockEl() });
        var mid  = sess._message.id;
        sess.push("old content"); sess.cancel();
        conv.retry(mid, mockEl());
        conv.cancelActive();
        return [
          eq(conv.getHistory()[0].rawText, "", "rawText cleared on retry"),
        ];
      },
    },

    {
      name: "retry-max-throws-on-exceed",
      run: function () {
        var conv = makeConv({ retryMax: 1 });
        var sess = conv.startMessage({ element: mockEl() });
        var mid  = sess._message.id;
        sess.cancel();
        conv.retry(mid, mockEl());
        conv.cancelActive();
        var threw = false;
        try { conv.retry(mid, mockEl()); } catch (e) { threw = true; }
        return ok(threw, "throws when retry count exceeds max");
      },
    },

    // ── History & replay ──────────────────────────────────────────────────
    {
      name: "history-append-only",
      run: function () {
        var conv = makeConv();
        var s1 = conv.startMessage({ element: mockEl() }); s1.push("msg1"); s1.finish();
        var s2 = conv.startMessage({ element: mockEl() }); s2.push("msg2"); s2.finish();
        return [
          eq(conv.getHistory().length, 2, "two messages in history"),
          eq(conv.getHistory()[0].rawText, "msg1", "first message intact"),
          eq(conv.getHistory()[1].rawText, "msg2", "second message intact"),
        ];
      },
    },

    {
      name: "history-getMessage",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ id: "known-id", element: mockEl() });
        sess.push("content"); sess.finish();
        var snap = conv.getMessage("known-id");
        return [
          ok(snap !== null, "getMessage returns snapshot"),
          eq(snap.id, "known-id", "correct id"),
          eq(snap.rawText, "content", "correct rawText"),
        ];
      },
    },

    {
      name: "replay-accuracy",
      run: function () {
        var conv   = makeConv();
        var el     = mockEl();
        var chunks = ["Hello ", "\\(x^2\\)", " world"];
        var result = null;
        conv.replay("replay-msg", chunks, el).then(function (snap) {
          result = snap;
        });
        // Replay with delay=0 resolves synchronously in same tick
        return [
          ok(el.innerHTML.length > 0, "replay populates element"),
          // rawText should equal concatenated chunks
          ok(
            (function () {
              var hist = conv.getHistory();
              var found = hist.filter(function (m) { return m.id === "replay-msg"; });
              return found.length > 0 && found[0].rawText === chunks.join("");
            })(),
            "replay rawText matches all chunks joined"
          ),
        ];
      },
    },

    // ── Stats & performance ───────────────────────────────────────────────
    {
      name: "stats-total-tokens",
      run: function () {
        var conv = makeConv();
        var s1 = conv.startMessage({ element: mockEl() });
        s1.push("a"); s1.push("b"); s1.push("c"); s1.finish();
        return eq(conv.getStats().totalTokens, 3, "totalTokens = 3 after 3 tokens");
      },
    },

    {
      name: "stats-total-cancels",
      run: function () {
        var conv = makeConv();
        var s1 = conv.startMessage({ element: mockEl() }); s1.push("x"); s1.cancel();
        var s2 = conv.startMessage({ element: mockEl() }); s2.push("y"); s2.cancel();
        return eq(conv.getStats().totalCancels, 2, "totalCancels = 2");
      },
    },

    {
      name: "stats-total-errors",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        conv.markFailed(sess._message.id, new Error("fail"));
        return eq(conv.getStats().totalErrors, 1, "totalErrors = 1 after markFailed()");
      },
    },

    {
      name: "perf-render-stats-set-after-flush",
      run: function () {
        // Only meaningful when streaming engine is available
        if (!global.AmiCorStreamingEngine) {
          return ok(true, "AmiCorStreamingEngine not available (skipped)");
        }
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("Test content \\(x = 1\\)"); sess.finish();
        var hist = conv.getHistory();
        return [
          ok(hist[0].renderStats !== null, "renderStats populated after flush"),
          ok(hist[0].renderStats.estimatedMemoryBytes > 0, "memory estimate > 0"),
        ];
      },
    },

    // ── Rapid burst / stress ──────────────────────────────────────────────
    {
      name: "stress-rapid-burst-100-chunks",
      run: function () {
        var conv = makeConv();
        var el   = mockEl();
        var sess = conv.startMessage({ element: el });
        for (var i = 0; i < 100; i++) { sess.push("word" + i + " "); }
        sess.finish();
        var snap = conv.getHistory()[0];
        return [
          eq(snap.tokenCount, 100, "100 tokens counted"),
          eq(snap.streamingState, "completed", "state = completed after burst"),
          ok(el.innerHTML.length > 0, "element populated"),
        ];
      },
    },

    // ── Multiple simultaneous conversations ───────────────────────────────
    {
      name: "simultaneous-conversations-isolated",
      run: function () {
        var conv1 = AmiCorOrchestrator.createConversation({ id: "sim1" });
        var conv2 = AmiCorOrchestrator.createConversation({ id: "sim2" });

        var s1 = conv1.startMessage({ element: mockEl() });
        var s2 = conv2.startMessage({ element: mockEl() });

        s1.push("conv1 text"); s1.finish();
        s2.push("conv2 text"); s2.finish();

        var results = [
          eq(conv1.getHistory()[0].rawText, "conv1 text", "conv1 history isolated"),
          eq(conv2.getHistory()[0].rawText, "conv2 text", "conv2 history isolated"),
          eq(conv1.getHistory().length, 1, "conv1 has 1 message"),
          eq(conv2.getHistory().length, 1, "conv2 has 1 message"),
        ];

        AmiCorOrchestrator.destroyConversation("sim1");
        AmiCorOrchestrator.destroyConversation("sim2");
        return results;
      },
    },

    // ── Destroy / cleanup ─────────────────────────────────────────────────
    {
      name: "destroy-clears-events",
      run: function () {
        var conv   = makeConv();
        var fired  = 0;
        conv.on("onMessageStart", function () { fired++; });
        conv.destroy();
        // After destroy, trying to startMessage should throw
        var threw = false;
        try { conv.startMessage({ element: mockEl() }); } catch (e) { threw = true; }
        return [
          ok(threw, "startMessage() throws after destroy()"),
          eq(fired, 0, "no events fired after destroy"),
        ];
      },
    },

    {
      name: "memory-cleanup-after-destroy",
      run: function () {
        var id   = "cleanup-conv-" + Date.now();
        var conv = AmiCorOrchestrator.createConversation({ id: id });
        var sess = conv.startMessage({ element: mockEl() });
        sess.push("data data data"); sess.finish();
        AmiCorOrchestrator.destroyConversation(id);
        return [
          ok(AmiCorOrchestrator.getConversation(id) === undefined, "conversation removed from registry"),
        ];
      },
    },

    // ── Malformed / edge input ────────────────────────────────────────────
    {
      name: "malformed-null-chunks",
      run: function () {
        var conv = makeConv();
        var sess = conv.startMessage({ element: mockEl() });
        sess.push(null); sess.push(undefined); sess.push(""); sess.push("real");
        sess.finish();
        return [
          eq(conv.getHistory()[0].rawText, "real", "only real text in rawText"),
        ];
      },
    },

    {
      name: "malformed-stream-xss",
      run: function () {
        var conv = makeConv();
        var el   = mockEl();
        var sess = conv.startMessage({ element: el });
        sess.push('<script>alert("xss")</script>');
        sess.finish();
        return lacks(el.innerHTML, "<script>", "XSS stripped from rendered output");
      },
    },

    {
      name: "partial-stream-recovery-after-cancel",
      run: function () {
        var conv = makeConv({ retryMax: 3 });
        var el1  = mockEl();
        var sess = conv.startMessage({ element: el1 });
        sess.push("Partial: \\(x = ");
        sess.cancel();

        // Retry — provide fresh element
        var el2    = mockEl();
        var sess2  = conv.retry(conv.getHistory()[0].id, el2);
        sess2.push("Full: \\(x = 5\\)");
        sess2.finish();

        return [
          eq(conv.getHistory()[0].rawText, "Full: \\(x = 5\\)", "after retry rawText is from new stream"),
          eq(conv.getHistory()[0].streamingState, "completed", "state = completed after retry"),
        ];
      },
    },

  ];

  // ─────────────────────────────────────────────────────────────────────────
  // Runner
  // ─────────────────────────────────────────────────────────────────────────

  function orchestratorTests(filter) {
    if (!global.AmiCorOrchestrator) {
      console.error("[orchestratorTests] AmiCorOrchestrator not found. Load orchestrator.js first.");
      return { passed: 0, failed: 1, total: 1 };
    }

    console.group(
      "%c AmiCorOrchestrator Test Suite",
      "font-weight:bold;font-size:14px;color:#ff9800"
    );
    console.time("orchestratorTests:total");

    var passed = 0;
    var failed = 0;

    for (var gi = 0; gi < groups.length; gi++) {
      var group = groups[gi];
      if (filter && group.name.indexOf(filter) === -1) continue;

      console.group("%c ● " + group.name, "font-weight:bold");
      console.time(group.name);

      var results;
      try {
        var raw = group.run();
        results = Array.isArray(raw) ? raw : [raw];
        // Flatten one level
        var flat = [];
        for (var ri = 0; ri < results.length; ri++) {
          var r = results[ri];
          if (Array.isArray(r)) { for (var si = 0; si < r.length; si++) flat.push(r[si]); }
          else flat.push(r);
        }
        results = flat;
      } catch (err) {
        results = [{ ok: false, desc: "(test group threw)", detail: String(err) }];
      }

      for (var ai = 0; ai < results.length; ai++) {
        var a = results[ai];
        if (!a) continue;
        if (a.ok) {
          console.log("  %c✓ " + a.desc, "color:#4caf50");
          passed++;
        } else {
          console.warn("  %c✗ " + a.desc, "color:#f44336");
          if (a.detail) console.warn("    " + String(a.detail).replace(/\n/g, "\n    "));
          failed++;
        }
      }

      console.timeEnd(group.name);
      console.groupEnd();
    }

    var total = passed + failed;
    console.timeEnd("orchestratorTests:total");

    var style = failed === 0
      ? "font-weight:bold;color:#4caf50"
      : "font-weight:bold;color:#f44336";
    console.log(
      "%c\n  Results: " + passed + "/" + total + " passed" + (failed > 0 ? ", " + failed + " FAILED" : " ✓"),
      style
    );
    console.groupEnd();

    return { passed: passed, failed: failed, total: total };
  }

  global.orchestratorTests = orchestratorTests;

})(window);
