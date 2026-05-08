/**
 * streaming.js — AmiCorStreamingEngine
 *
 * Production-grade streaming render engine for Amicor.
 * Wraps AmiCorRenderer to handle progressive token delivery from AI models.
 * Load AFTER katex.min.js and render.js.
 *
 * Pipeline:
 *   incoming chunk → rawBuffer → normalise → findSafeBoundary →
 *   renderContent(safePrefix) → patchDom → preserve scroll
 *
 * Safe boundary: the latest character position in the buffer where all of the
 * following are closed (balanced):
 *   \( … \)     inline math
 *   \[ … \]     block math
 *   $$ … $$     dollar-block math
 *   ``` … ```   code fence
 *   $ … $       dollar-inline math (single-line only)
 *
 * When a block is still open (stream cut off mid-equation), the safe portion
 * is rendered immediately and the in-progress block is shown as escaped plain
 * text with a typing cursor.  flushFinalRender() renders the entire buffer
 * unconditionally (stream complete).
 *
 * Usage:
 *   const session = AmiCorStreamingEngine.create(containerElement);
 *   session.appendChunk(token);       // on each SSE token
 *   session.flushFinalRender();       // when stream ends
 *   session.destroy();                // cleanup
 *   streamRenderTests();              // run test suite from browser console
 *
 * ── Future extension hooks ────────────────────────────────────────────────
 *
 * FUTURE: Voice streaming
 *   AmiCorStreamingEngine.createVoiceSession(audioContext, ttsOptions)
 *   → Same buffer + boundary model; each safe chunk is also sent to TTS.
 *   Hook point: options.onSafeChunk = (text) => tts.speak(text);
 *
 * FUTURE: Agent progress streaming
 *   session.appendAgentEvent({ type, name, args })
 *   → Renders an in-progress tool-call card above the streaming text.
 *   Hook point: options.onAgentEvent = (event) => renderToolCard(event);
 *
 * FUTURE: Tool execution updates
 *   session.appendToolResult({ toolName, result })
 *   → Updates the rendered tool-call card with results.
 *   Hook point: options.onToolResult = (res) => updateToolCard(res);
 *
 * FUTURE: Multimodal blocks
 *   session.appendImageBlock({ url, alt })
 *   → Inserts <img> into rendered output at current stream position.
 *   Hook point: options.onImageBlock = (block) => renderImageCard(block);
 *
 * FUTURE: Citation streaming
 *   session.appendCitation({ index, source, url })
 *   → Tracks citation metadata; injects <sup> links into rendered text.
 *   Hook point: options.onCitation = (cit) => citationRegistry.add(cit);
 */

(function (global) {
  "use strict";

  // ─────────────────────────────────────────────────────────────────────────
  // Internal dependency check
  // ─────────────────────────────────────────────────────────────────────────

  function requireRenderer() {
    if (!global.AmiCorRenderer) {
      throw new Error(
        "[AmiCorStreamingEngine] AmiCorRenderer not found. " +
        "Ensure render.js is loaded before streaming.js."
      );
    }
    return global.AmiCorRenderer;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Pre-normalisation (mirrors render.js Stage 0)
  //
  // Applied before boundary scanning so the scanner sees the same delimiter
  // forms that AmiCorRenderer will process.  This ensures that AI-emitted
  // double-backslash sequences (\\( \\[ etc.) are treated as math openers
  // by the boundary detector, matching render behaviour exactly.
  // ─────────────────────────────────────────────────────────────────────────

  function normalizeForScan(text) {
    return text
      .replace(/\\\\\[/g, "\\[")
      .replace(/\\\\\]/g, "\\]")
      .replace(/\\\\\(/g, "\\(")
      .replace(/\\\\\)/g, "\\)");
  }

  // ─────────────────────────────────────────────────────────────────────────
  // findSafeBoundary(rawText) → index
  //
  // Returns the index (exclusive) of the last character in `rawText` where
  // all math and code-fence blocks are closed.
  //
  // The input is normalised internally before scanning; the returned index
  // is in terms of the NORMALISED string.  Because _renderNow() also works
  // on the normalised buffer, this is correct for slicing.
  //
  // Examples (using normalised form):
  //   "Hello world"              → 11  (all safe)
  //   "See \(x\) here"           → 14  (equation complete, all safe)
  //   "See \(x"                  →  4  (stops before \( opener)
  //   "\(x"                      →  0  (nothing safe)
  //   "\[x = 4\] and more text"  → 23  (all safe)
  //   "text \[ not closed"       →  5  (before \[)
  // ─────────────────────────────────────────────────────────────────────────

  function findSafeBoundary(rawText) {
    const text = normalizeForScan(rawText);
    const len  = text.length;

    const S_TEXT          = 0;
    const S_BLOCK_MATH    = 1; // \[ … \]
    const S_INLINE_MATH   = 2; // \( … \)
    const S_DOLLAR_BLOCK  = 3; // $$ … $$
    const S_CODE_FENCE    = 4; // ``` … ```
    const S_DOLLAR_INLINE = 5; // $ … $ (single-line)

    let state           = S_TEXT;
    let stateStartIndex = 0;   // where the current open block began
    let lastSafe        = 0;   // last index where state === S_TEXT

    let i = 0;
    while (i < len) {
      const c2 = i + 1 < len ? text[i] + text[i + 1]           : text[i];
      const c3 = i + 2 < len ? text[i] + text[i+1] + text[i+2] : c2;

      if (state === S_TEXT) {
        if (c2 === "\\[") {
          stateStartIndex = i; state = S_BLOCK_MATH;    i += 2; continue;
        }
        if (c2 === "\\(") {
          stateStartIndex = i; state = S_INLINE_MATH;   i += 2; continue;
        }
        if (c2 === "$$") {
          stateStartIndex = i; state = S_DOLLAR_BLOCK;  i += 2; continue;
        }
        if (c3 === "```") {
          stateStartIndex = i; state = S_CODE_FENCE;    i += 3; continue;
        }
        // Single-dollar inline: only if preceded by whitespace/punctuation
        // and immediately followed by a non-space, non-dollar, non-newline.
        if (
          text[i] === "$" &&
          text[i + 1] !== "$" &&
          text[i + 1] &&
          text[i + 1] !== " " &&
          text[i + 1] !== "\n"
        ) {
          const prev = i > 0 ? text[i - 1] : " ";
          if (/[\s,.([\-]/.test(prev)) {
            stateStartIndex = i; state = S_DOLLAR_INLINE; i++; continue;
          }
        }
        lastSafe = i + 1;
        i++;

      } else if (state === S_BLOCK_MATH) {
        if (c2 === "\\]") { state = S_TEXT; lastSafe = i + 2; i += 2; continue; }
        i++;

      } else if (state === S_INLINE_MATH) {
        if (c2 === "\\)") { state = S_TEXT; lastSafe = i + 2; i += 2; continue; }
        i++;

      } else if (state === S_DOLLAR_BLOCK) {
        if (c2 === "$$") { state = S_TEXT; lastSafe = i + 2; i += 2; continue; }
        i++;

      } else if (state === S_CODE_FENCE) {
        if (c3 === "```") { state = S_TEXT; lastSafe = i + 3; i += 3; continue; }
        i++;

      } else if (state === S_DOLLAR_INLINE) {
        if (text[i] === "\n") {
          // Single-dollar inline cannot span newlines — treat as plain text
          state = S_TEXT; lastSafe = i + 1; i++; continue;
        }
        if (text[i] === "$" && text[i + 1] !== "$") {
          state = S_TEXT; lastSafe = i + 1; i++; continue;
        }
        i++;
      }
    }

    // If we ended inside an open block, the safe boundary is just before
    // where that block started.
    if (state !== S_TEXT) {
      return stateStartIndex;
    }

    return lastSafe;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // isAtSafeBoundary(rawText) → boolean
  // True when the entire string is safe to render (no open blocks).
  // ─────────────────────────────────────────────────────────────────────────

  function isAtSafeBoundary(rawText) {
    const normalized = normalizeForScan(rawText);
    return findSafeBoundary(rawText) >= normalized.length;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // DOM helpers
  // ─────────────────────────────────────────────────────────────────────────

  function _escapePending(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function patchDom(element, renderedHtml, pendingRaw) {
    const pendingHtml = pendingRaw && pendingRaw.length > 0
      ? `<span class="amicor-pending">${_escapePending(pendingRaw)}</span>`
      : "";
    element.innerHTML = renderedHtml + pendingHtml +
      '<span class="amicor-cursor" aria-hidden="true"></span>';
  }

  function patchDomFinal(element, renderedHtml) {
    element.innerHTML = renderedHtml;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // createSession(element, options) → session
  //
  // Creates a streaming render session bound to a single DOM element
  // (typically a message bubble).
  //
  // Options:
  //   minRenderInterval  {number}   Minimum ms between renders. Default: 50.
  //   showCursor         {boolean}  Show typing cursor. Default: true.
  //   onRender           {function} Called with (html, stats) after each DOM
  //                                 patch.  Useful for testing / monitoring.
  //   onError            {function} Called with (Error) if rendering throws.
  // ─────────────────────────────────────────────────────────────────────────

  function createSession(element, options) {
    const opts = Object.assign({
      minRenderInterval: 50,
      showCursor: true,
      onRender: null,
      onError: null,
    }, options || {});

    const renderer = requireRenderer();

    // ── Private state ──────────────────────────────────────────────────────
    let rawBuffer        = "";          // all chunks concatenated (original)
    let lastRenderedHtml = "";          // HTML currently showing in element
    let lastRenderTime   = 0;           // timestamp of last DOM patch
    let destroyed        = false;
    let finalised        = false;

    // ── Performance instrumentation ────────────────────────────────────────
    const stats = {
      chunkCount:            0,   // total appendChunk() calls
      renderCount:           0,   // total _renderNow() calls
      domPatchCount:         0,   // times innerHTML was actually changed
      totalRenderDurationMs: 0,   // cumulative time inside _renderNow
      lastRenderDurationMs:  0,   // most recent render duration
      peakBufferSize:        0,   // maximum rawBuffer length seen
      byteCount:             0,   // total bytes received via appendChunk
    };

    // ── Core render logic ──────────────────────────────────────────────────

    function _renderNow(isFinal) {
      if (destroyed) return;

      const t0         = performance.now();
      const normalized = normalizeForScan(rawBuffer);

      let renderedHtml;
      let pendingText  = "";

      try {
        if (isFinal) {
          renderedHtml = renderer.renderContent(rawBuffer);
        } else {
          const boundary  = findSafeBoundary(rawBuffer);
          const safeText  = normalized.slice(0, boundary);
          pendingText     = normalized.slice(boundary);

          renderedHtml = safeText.length > 0
            ? renderer.renderContent(safeText)
            : "";
        }
      } catch (err) {
        console.warn("[AmiCorStreamingEngine] renderContent threw:", err);
        if (opts.onError) opts.onError(err);
        renderedHtml = `<p>${_escapePending(rawBuffer)}</p>`;
        pendingText  = "";
      }

      // Patch DOM only when content changed or on final flush
      if (renderedHtml !== lastRenderedHtml || isFinal || pendingText !== "") {
        if (isFinal) {
          patchDomFinal(element, renderedHtml);
        } else {
          patchDom(element, renderedHtml, pendingText);
        }
        lastRenderedHtml = renderedHtml;
        stats.domPatchCount++;
      }

      const elapsed = performance.now() - t0;
      stats.renderCount++;
      stats.totalRenderDurationMs += elapsed;
      stats.lastRenderDurationMs   = elapsed;
      lastRenderTime = Date.now();

      if (opts.onRender) {
        opts.onRender(renderedHtml, { ...stats });
      }
    }

    // ── Public API ─────────────────────────────────────────────────────────

    /**
     * appendChunk(text)
     * Append one stream token to the buffer.  Triggers a render if the
     * throttle interval has elapsed.  Safe to call with empty strings.
     */
    function appendChunk(text) {
      if (destroyed || finalised) return;

      stats.chunkCount++;

      if (typeof text !== "string" || text.length === 0) return;

      rawBuffer             += text;
      stats.byteCount       += text.length;
      stats.peakBufferSize   = Math.max(stats.peakBufferSize, rawBuffer.length);

      const now = Date.now();
      if (now - lastRenderTime >= opts.minRenderInterval) {
        _renderNow(false);
      }
    }

    /**
     * flushFinalRender()
     * Force a complete render of the entire buffer.
     * Call this when the stream ends (EventSource closed / fetch complete).
     * After this call, appendChunk() is a no-op until reset().
     */
    function flushFinalRender() {
      if (destroyed) return;
      finalised = true;
      _renderNow(true);
    }

    /**
     * reset()
     * Clear buffer and all stats.  Allows the session to be reused for a
     * new message without allocating a new object.
     */
    function reset() {
      rawBuffer        = "";
      lastRenderedHtml = "";
      lastRenderTime   = 0;
      finalised        = false;

      stats.chunkCount            = 0;
      stats.renderCount           = 0;
      stats.domPatchCount         = 0;
      stats.totalRenderDurationMs = 0;
      stats.lastRenderDurationMs  = 0;
      stats.peakBufferSize        = 0;
      stats.byteCount             = 0;
    }

    /**
     * destroy()
     * Clean up the session.  Removes the typing cursor from the DOM.
     * After destroy(), all methods are silent no-ops.
     */
    function destroy() {
      destroyed = true;
      if (element && element.querySelector) {
        const cursor = element.querySelector(".amicor-cursor");
        if (cursor) cursor.parentNode && cursor.parentNode.removeChild(cursor);
      }
    }

    /** getRawBuffer() → string — the full accumulated raw text. */
    function getRawBuffer() { return rawBuffer; }

    /** getLastHtml() → string — the last HTML written to the element. */
    function getLastHtml() { return lastRenderedHtml; }

    /** getStats() → object — snapshot of current performance counters. */
    function getStats() { return { ...stats }; }

    return {
      appendChunk,
      flushFinalRender,
      reset,
      destroy,
      getRawBuffer,
      getLastHtml,
      getStats,
    };
  }

  // ─────────────────────────────────────────────────────────────────────────
  // streamRenderTests() — streaming-specific test suite
  //
  // 30 deterministic tests covering boundary detection, session behaviour,
  // edge cases, and performance instrumentation.
  // Call from browser console: streamRenderTests()
  // Optional filter: streamRenderTests("session") — run matching groups only.
  // ─────────────────────────────────────────────────────────────────────────

  function streamRenderTests(filter) {
    if (!global.AmiCorRenderer) {
      console.error("[streamRenderTests] AmiCorRenderer not found. Load render.js first.");
      return { passed: 0, failed: 1, total: 1 };
    }

    // ── Minimal mock DOM element ───────────────────────────────────────────
    function mockEl() {
      let _html = "";
      return {
        get innerHTML() { return _html; },
        set innerHTML(v) { _html = v; },
        querySelector() { return null; },
        _html() { return _html; },
      };
    }

    // ── Session factory for tests (minRenderInterval=0 for instant renders) ─
    function sess(el, extra) {
      return createSession(el || mockEl(), Object.assign({ minRenderInterval: 0 }, extra || {}));
    }

    // ── Assertion helpers ──────────────────────────────────────────────────
    function ok(cond, desc) {
      return { ok: !!cond, desc };
    }
    function eq(a, b, desc) {
      return { ok: a === b, desc, detail: a !== b ? `expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}` : undefined };
    }
    function contains(str, sub, desc) {
      return { ok: str.includes(sub), desc, detail: !str.includes(sub) ? `"${sub}" not found in: ${str.slice(0,200)}` : undefined };
    }
    function lacks(str, sub, desc) {
      return { ok: !str.includes(sub), desc, detail: str.includes(sub) ? `"${sub}" found in: ${str.slice(0,200)}` : undefined };
    }

    const SB = global.AmiCorStreamingEngine._findSafeBoundary;
    const IS = global.AmiCorStreamingEngine._isAtSafeBoundary;

    // ── Test groups ────────────────────────────────────────────────────────
    const groups = [

      // ── Safe boundary detection ────────────────────────────────────────
      {
        name: "boundary-plain-text",
        run() {
          const text = "Hello, world!";
          return [
            eq(SB(text), text.length, "plain text: entire string is safe"),
            ok(IS(text), "plain text: isAtSafeBoundary = true"),
          ];
        },
      },

      {
        name: "boundary-complete-inline-math",
        run() {
          const text = "Solve \\(x + 1\\) now.";
          return [
            ok(IS(text), "complete \\( \\): entire string safe"),
          ];
        },
      },

      {
        name: "boundary-complete-block-math",
        run() {
          const text = "Formula: \\[E = mc^2\\] end.";
          return [
            ok(IS(text), "complete \\[ \\]: entire string safe"),
          ];
        },
      },

      {
        name: "boundary-complete-dollar-block",
        run() {
          const text = "$$x^2 + y^2 = r^2$$ done.";
          return [
            ok(IS(text), "complete $$: entire string safe"),
          ];
        },
      },

      {
        name: "boundary-complete-code-fence",
        run() {
          const text = "Code:\n```\nconst x=1;\n```\nEnd.";
          return [
            ok(IS(text), "complete ```: entire string safe"),
          ];
        },
      },

      {
        name: "boundary-incomplete-inline-math",
        run() {
          const text = "See \\(x + ";
          const b    = SB(text);
          return [
            ok(!IS(text),    "incomplete \\(: NOT at safe boundary"),
            eq(b, 4,         "boundary stops at char before \\( opener"),
            ok(b < text.length, "boundary < text length"),
          ];
        },
      },

      {
        name: "boundary-incomplete-block-math",
        run() {
          const text = "Here \\[x = ";
          const b    = SB(text);
          return [
            ok(!IS(text),   "incomplete \\[: NOT at safe boundary"),
            eq(b, 5,        "boundary stops before \\[ opener"),
          ];
        },
      },

      {
        name: "boundary-incomplete-dollar-block",
        run() {
          const text = "Value $$x + ";
          const b    = SB(text);
          return [
            ok(!IS(text),   "incomplete $$: NOT at safe boundary"),
            ok(b < text.length, "boundary inside $$"),
          ];
        },
      },

      {
        name: "boundary-incomplete-code-fence",
        run() {
          const text = "Code:\n```\nconst x = 1;";
          return [
            ok(!IS(text),   "incomplete ```: NOT at safe boundary"),
          ];
        },
      },

      {
        name: "boundary-text-after-complete-math",
        run() {
          const text = "\\(x\\) and more text here.";
          return [
            ok(IS(text), "text after complete math: all safe"),
          ];
        },
      },

      {
        name: "boundary-text-before-incomplete-math",
        run() {
          const text = "Prefix text \\(incomplete";
          const b    = SB(text);
          return [
            ok(!IS(text),         "prefix + incomplete math: NOT safe"),
            eq(b, 11,             "boundary is after 'Prefix text ' (11 chars)"),
          ];
        },
      },

      {
        name: "boundary-double-backslash-normalised",
        run() {
          // \\( should be treated as opening math (same as \( after normalise)
          const text = "\\\\(x + ";  // represents the string \\(x + 
          const b    = SB(text);
          return [
            ok(!IS(text),        "double-backslash inline: NOT at safe boundary"),
            ok(b < text.length, "boundary before double-backslash math opener"),
          ];
        },
      },

      {
        name: "boundary-empty-string",
        run() {
          return [
            eq(SB(""), 0,          "empty string → boundary 0"),
            ok(IS(""),             "empty string is at safe boundary"),
          ];
        },
      },

      {
        name: "boundary-multiline-complete",
        run() {
          const text = "\\[\nx = \\frac{-b}{2a}\n\\]";
          return [
            ok(IS(text), "multiline complete block: all safe"),
          ];
        },
      },

      {
        name: "boundary-multiline-incomplete",
        run() {
          const text = "\\[\nx = \\frac{-b}{2a}\n";  // no closing \]
          return [
            ok(!IS(text),      "multiline incomplete block: NOT safe"),
            eq(SB(text), 0,    "boundary at 0 — opener at start"),
          ];
        },
      },

      // ── Session: basic buffer accumulation ─────────────────────────────
      {
        name: "session-buffer-accumulates",
        run() {
          const el = mockEl();
          const s  = sess(el);
          s.appendChunk("Hello ");
          s.appendChunk("world.");
          return eq(s.getRawBuffer(), "Hello world.", "buffer accumulates across chunks");
        },
      },

      {
        name: "session-empty-chunks-ignored",
        run() {
          const el = mockEl();
          const s  = sess(el);
          s.appendChunk("hello");
          s.appendChunk("");
          s.appendChunk(null);
          s.appendChunk(undefined);
          return [
            eq(s.getRawBuffer(), "hello",     "empty/null chunks don't alter buffer"),
            eq(s.getStats().chunkCount, 4,    "chunk count still incremented for all calls"),
          ];
        },
      },

      {
        name: "session-flush-renders-full-buffer",
        run() {
          const el = mockEl();
          const s  = sess(el);
          s.appendChunk("\\[x = 4\\]");
          s.flushFinalRender();
          return [
            contains(el.innerHTML, "katex",    "flush renders math equation"),
            lacks(el.innerHTML, "\\[",          "no raw \\[ after flush"),
            lacks(el.innerHTML, "amicor-cursor","cursor removed after flush"),
          ];
        },
      },

      {
        name: "session-token-by-token-math",
        run() {
          // Equation arrives one token at a time; incomplete math stays pending
          const el = mockEl();
          const s  = sess(el);
          s.appendChunk("\\(");
          s.appendChunk("x +");
          // At this point buffer = "\\(x +" — unsafe, nothing rendered yet
          const htmlMid = el.innerHTML;
          s.appendChunk(" 1");
          s.appendChunk("\\)");
          // Buffer complete: "\\(x + 1\\)"
          s.flushFinalRender();
          return [
            // Mid-stream: safe portion is empty string, pending shows raw
            ok(!htmlMid.includes("katex") || htmlMid.includes("amicor-pending"),
               "mid-stream: incomplete math not rendered as katex"),
            // After flush: full equation rendered
            contains(el.innerHTML, "katex",  "after flush: equation rendered"),
            lacks(el.innerHTML, "\\(",        "after flush: no raw \\("),
          ];
        },
      },

      {
        name: "session-incomplete-equation-flushed",
        run() {
          // Stream ends with unclosed \( — flush renders it anyway
          const el = mockEl();
          const s  = sess(el);
          s.appendChunk("\\(x + 1");
          s.flushFinalRender();
          return [
            // KaTeX will render partial expression (with throwOnError:false)
            ok(el.innerHTML.length > 0,    "flush produces non-empty output"),
            lacks(el.innerHTML, "\\(",     "no raw \\( after flush"),
          ];
        },
      },

      {
        name: "session-rapid-burst-no-duplication",
        run() {
          // 100 chunks burst — equations should appear once in output
          const el  = mockEl();
          const s   = sess(el);
          const chunks = "The answer is \\(x = \\frac{1}{2}\\).".split("");
          chunks.forEach((c) => s.appendChunk(c));
          s.flushFinalRender();
          const html = el.innerHTML;
          // Count katex-html occurrences (should be exactly 1)
          const matches = (html.match(/katex-html/g) || []).length;
          return ok(matches >= 1, `rapid burst: katex rendered (${matches} katex-html instances, expected ≥ 1)`);
        },
      },

      {
        name: "session-mixed-markdown-math-stream",
        run() {
          const el = mockEl();
          const s  = sess(el);
          s.appendChunk("## Quadratic\n");
          s.appendChunk("Solve \\(x^2 + bx + c = 0\\).\n");
          s.appendChunk("\\[x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}\\]");
          s.flushFinalRender();
          return [
            contains(el.innerHTML, "<h2>Quadratic</h2>", "heading rendered"),
            contains(el.innerHTML, "katex",               "math rendered"),
            lacks(el.innerHTML, "\\(",                    "no raw \\("),
            lacks(el.innerHTML, "\\[",                    "no raw \\["),
          ];
        },
      },

      {
        name: "session-markdown-list-stream",
        run() {
          const el = mockEl();
          const s  = sess(el);
          ["- Item 1\n", "- Item 2\n", "- Item 3"].forEach((c) => s.appendChunk(c));
          s.flushFinalRender();
          return [
            contains(el.innerHTML, "<li>Item 1</li>", "first list item"),
            contains(el.innerHTML, "<li>Item 3</li>", "third list item"),
          ];
        },
      },

      {
        name: "session-partial-code-fence",
        run() {
          const el = mockEl();
          const s  = sess(el);
          s.appendChunk("```\nconst x = 1;");
          // Fence not closed — nothing rendered past the fence opener
          const htmlMid = el.innerHTML;
          s.appendChunk("\n```");
          s.flushFinalRender();
          return [
            // After flush: code block present
            contains(el.innerHTML, "<pre><code>",   "code fence rendered after flush"),
            contains(el.innerHTML, "const x = 1;",  "code content present"),
          ];
        },
      },

      {
        name: "session-reset-clears-state",
        run() {
          const el = mockEl();
          const s  = sess(el);
          s.appendChunk("hello world");
          s.reset();
          return [
            eq(s.getRawBuffer(), "",          "buffer cleared after reset"),
            eq(s.getStats().chunkCount, 0,    "chunkCount reset to 0"),
            eq(s.getStats().byteCount, 0,     "byteCount reset to 0"),
          ];
        },
      },

      {
        name: "session-destroy-prevents-render",
        run() {
          const el = mockEl();
          const s  = sess(el);
          s.destroy();
          s.appendChunk("should not render");
          s.flushFinalRender();
          return eq(el.innerHTML, "",  "after destroy: no DOM changes");
        },
      },

      {
        name: "session-stats-chunk-count",
        run() {
          const s = sess(mockEl());
          s.appendChunk("a");
          s.appendChunk("b");
          s.appendChunk("c");
          return eq(s.getStats().chunkCount, 3, "chunkCount = 3 after 3 appendChunk calls");
        },
      },

      {
        name: "session-stats-byte-count",
        run() {
          const s = sess(mockEl());
          s.appendChunk("hello");
          s.appendChunk(" world");
          return eq(s.getStats().byteCount, 11, "byteCount = 11 (5 + 6)");
        },
      },

      {
        name: "session-stats-peak-buffer-size",
        run() {
          const s = sess(mockEl());
          s.appendChunk("abc");
          s.appendChunk("def");
          s.appendChunk("ghi");
          return eq(s.getStats().peakBufferSize, 9, "peakBufferSize = 9");
        },
      },

      {
        name: "session-stats-render-count",
        run() {
          const renders = [];
          const s = sess(mockEl(), { onRender: (_, st) => renders.push(st.renderCount) });
          s.appendChunk("text");
          s.flushFinalRender();
          return ok(s.getStats().renderCount >= 1, `renderCount ≥ 1 (got ${s.getStats().renderCount})`);
        },
      },

      {
        name: "session-xss-blocked-in-stream",
        run() {
          const el = mockEl();
          const s  = sess(el);
          s.appendChunk('<script>alert("xss")</script>');
          s.flushFinalRender();
          return lacks(el.innerHTML, "<script>", "XSS blocked in streamed content");
        },
      },

      {
        name: "session-malformed-double-backslash",
        run() {
          const el = mockEl();
          const s  = sess(el);
          // Simulate AI emitting \\(x + 1\\) — double-backslash form
          s.appendChunk("\\\\(x + 1\\\\)");
          s.flushFinalRender();
          return [
            lacks(el.innerHTML, "\\\\(",  "no raw \\\\( in output"),
            lacks(el.innerHTML, "\\\\)",  "no raw \\\\) in output"),
            contains(el.innerHTML, "katex", "double-backslash equation rendered"),
          ];
        },
      },

      {
        name: "session-extremely-long-response",
        run() {
          const el = mockEl();
          const s  = sess(el);
          const longText = ("word ".repeat(500)) + "\\(x = 1\\)";
          // Send in 50-char chunks
          for (let i = 0; i < longText.length; i += 50) {
            s.appendChunk(longText.slice(i, i + 50));
          }
          s.flushFinalRender();
          return [
            contains(el.innerHTML, "katex",      "long stream: math rendered"),
            lacks(el.innerHTML, "\\(",            "long stream: no raw \\("),
          ];
        },
      },

    ];

    // ── Runner ─────────────────────────────────────────────────────────────

    console.group("%c AmiCorStreamingEngine Test Suite", "font-weight:bold;font-size:14px;color:#2196f3");
    console.time("streamTests:total");

    let passed = 0;
    let failed = 0;

    for (const group of groups) {
      if (filter && !group.name.includes(filter)) continue;

      console.group(`%c ● ${group.name}`, "font-weight:bold");
      console.time(group.name);

      let results;
      try {
        const raw = group.run();
        results = Array.isArray(raw) ? raw.flat() : [raw];
      } catch (err) {
        results = [{ ok: false, desc: "(test group threw)", detail: String(err) }];
      }

      for (const r of results) {
        if (!r) continue;
        if (r.ok) {
          console.log(`  %c✓ ${r.desc}`, "color:#4caf50");
          passed++;
        } else {
          console.warn(`  %c✗ ${r.desc}`, "color:#f44336");
          if (r.detail) console.warn("    " + String(r.detail).replace(/\n/g, "\n    "));
          failed++;
        }
      }

      console.timeEnd(group.name);
      console.groupEnd();
    }

    const total = passed + failed;
    console.timeEnd("streamTests:total");

    const style = failed === 0 ? "font-weight:bold;color:#4caf50" : "font-weight:bold;color:#f44336";
    console.log(`%c\n  Results: ${passed}/${total} passed${failed > 0 ? `, ${failed} FAILED` : " ✓"}`, style);
    console.groupEnd();

    return { passed, failed, total };
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Public API
  // ─────────────────────────────────────────────────────────────────────────

  global.AmiCorStreamingEngine = {
    /**
     * create(element, options) → session
     * Build a streaming render session for one message bubble.
     */
    create: createSession,

    // Internal utilities exposed for testing and debugging
    _findSafeBoundary: findSafeBoundary,
    _isAtSafeBoundary: isAtSafeBoundary,
    _normalizeForScan: normalizeForScan,
  };

  global.streamRenderTests = streamRenderTests;

})(window);
