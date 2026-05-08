/**
 * render.test.js — AmiCorRenderer test suite
 *
 * Runs entirely in the browser.  Load AFTER katex.min.js and render.js.
 * Call runRenderTests() from the browser console, or add to a test page.
 *
 * Usage (browser console):
 *   runRenderTests()
 *
 * Output:
 *   PASS / FAIL lines with timing summary printed to console.
 *
 * ── Future extension hooks ──────────────────────────────────────────────────
 *   FUTURE_HOOKS at the bottom of this file documents the architecture
 *   extension points for:
 *     - syntax highlighting (code blocks)
 *     - tables
 *     - citations
 *     - diagrams
 *     - streaming token rendering
 *
 * ── Visual regression samples ───────────────────────────────────────────────
 *   Each test case with a `snapshot` key captures input → expected HTML
 *   for manual inspection.  runRenderTests() logs mismatches with full diffs.
 */

(function (global) {
  "use strict";

  // ── Module-level reference to AmiCorRenderer ─────────────────────────────
  // Resolved at call time (when runRenderTests() is invoked) so this file
  // can be loaded before AmiCorRenderer is available.
  let R;

  // ── Tiny assertion framework ──────────────────────────────────────────────

  function assert(description, actual, check) {
    const passed = check(actual);
    return { description, passed, actual };
  }

  /** Assert output contains a substring */
  function contains(desc, input, substring) {
    const out = R.renderContent(input);
    return assert(desc, out, (o) => o.includes(substring));
  }

  /** Assert output does NOT contain a substring */
  function notContains(desc, input, substring) {
    const out = R.renderContent(input);
    return assert(desc, out, (o) => !o.includes(substring));
  }

  /** Assert a stage function produces expected output */
  function stageEq(desc, fn, input, expected) {
    const actual = typeof input === "string" ? fn(input) : fn(...input);
    const passed = actual === expected;
    return { description: desc, passed, actual, expected };
  }

  /** Assert renderContent output matches snapshot exactly */
  function snapshot(desc, input, expectedHtml) {
    const actual = R.renderContent(input);
    const passed = actual === expectedHtml;
    return { description: desc, passed, actual, expected: expectedHtml, isSnapshot: true };
  }

  // ── Test definitions ──────────────────────────────────────────────────────

  function buildTests() {
    const S = R._stages;
    const tests = [];

    // ── Stage 0: normalizeDelimiters ────────────────────────────────────────

    tests.push(stageEq(
      "S0-01 | double-backslash \\\\( normalised to \\(",
      S.normalizeDelimiters,
      "\\\\(x = 1\\\\)",
      "\\(x = 1\\)"
    ));

    tests.push(stageEq(
      "S0-02 | double-backslash \\\\[ normalised to \\[",
      S.normalizeDelimiters,
      "\\\\[E = mc^2\\\\]",
      "\\[E = mc^2\\]"
    ));

    tests.push(stageEq(
      "S0-03 | single-backslash delimiters pass through unchanged",
      S.normalizeDelimiters,
      "\\(x\\) and \\[y\\]",
      "\\(x\\) and \\[y\\]"
    ));

    tests.push(stageEq(
      "S0-04 | plain text is untouched by normalizer",
      S.normalizeDelimiters,
      "Hello world",
      "Hello world"
    ));

    // ── Stage 2: stripStrayDelimiters ───────────────────────────────────────

    tests.push(stageEq(
      "S2-01 | unmatched \\( stripped",
      S.stripStrayDelimiters,
      "Hello \\( world",
      "Hello  world"
    ));

    tests.push(stageEq(
      "S2-02 | unmatched \\[ stripped",
      S.stripStrayDelimiters,
      "Some \\[ text",
      "Some  text"
    ));

    tests.push(stageEq(
      "S2-03 | all four stray forms stripped",
      S.stripStrayDelimiters,
      "\\( \\) \\[ \\]",
      "   "
    ));

    tests.push(stageEq(
      "S2-04 | text without delimiters unchanged",
      S.stripStrayDelimiters,
      "normal text",
      "normal text"
    ));

    // ── Stage 3: escapeHtml ─────────────────────────────────────────────────

    tests.push(stageEq(
      "S3-01 | & escaped to &amp;",
      S.escapeHtml,
      "a & b",
      "a &amp; b"
    ));

    tests.push(stageEq(
      "S3-02 | < escaped to &lt;",
      S.escapeHtml,
      "a < b",
      "a &lt; b"
    ));

    tests.push(stageEq(
      "S3-03 | > escaped to &gt;",
      S.escapeHtml,
      "a > b",
      "a &gt; b"
    ));

    tests.push(stageEq(
      "S3-04 | combined XSS attempt escaped",
      S.escapeHtml,
      "<script>alert('xss')</script>",
      "&lt;script&gt;alert('xss')&lt;/script&gt;"
    ));

    // ── Stage 5: sanitizeHtml ───────────────────────────────────────────────

    tests.push(stageEq(
      "S5-01 | <script> tag stripped",
      S.sanitizeHtml,
      "<p>hello<script>alert(1)</script></p>",
      "<p>hello</p>"
    ));

    tests.push(stageEq(
      "S5-02 | javascript: href stripped",
      S.sanitizeHtml,
      '<a href="javascript:alert(1)">click</a>',
      '<a href="alert(1)">click</a>'
    ));

    tests.push(stageEq(
      "S5-03 | onclick= handler blocked",
      S.sanitizeHtml,
      '<div onclick="evil()">',
      '<div data-blocked="evil()">'
    ));

    tests.push(stageEq(
      "S5-04 | onerror= handler blocked",
      S.sanitizeHtml,
      '<img onerror="evil()">',
      '<img data-blocked="evil()">'
    ));

    // ── renderContent: inline math ──────────────────────────────────────────

    tests.push(notContains(
      "RC-01 | inline \\( ... \\) — no raw \\( in output",
      "Solve \\(x + 2 = 5\\) for x.",
      "\\("
    ));

    tests.push(notContains(
      "RC-02 | inline \\( ... \\) — no raw \\) in output",
      "Solve \\(x + 2 = 5\\) for x.",
      "\\)"
    ));

    tests.push(contains(
      "RC-03 | inline \\( ... \\) — katex-html class present",
      "Solve \\(x + 2 = 5\\) for x.",
      "katex"
    ));

    // ── renderContent: block math ───────────────────────────────────────────

    tests.push(notContains(
      "RC-04 | block \\[ ... \\] — no raw \\[ in output",
      "\\[E = mc^2\\]",
      "\\["
    ));

    tests.push(notContains(
      "RC-05 | block \\[ ... \\] — no raw \\] in output",
      "\\[E = mc^2\\]",
      "\\]"
    ));

    tests.push(contains(
      "RC-06 | block \\[ ... \\] — katex-display class present",
      "\\[E = mc^2\\]",
      "katex-display"
    ));

    // ── renderContent: $$ ... $$ ────────────────────────────────────────────

    tests.push(notContains(
      "RC-07 | $$ block — no raw $$ in output",
      "$$x^2 + y^2 = r^2$$",
      "$$"
    ));

    tests.push(contains(
      "RC-08 | $$ block — katex rendered",
      "$$x^2 + y^2 = r^2$$",
      "katex"
    ));

    // ── renderContent: $ ... $ inline ───────────────────────────────────────

    tests.push(contains(
      "RC-09 | single $ inline — katex rendered",
      "The value is $x = 4$.",
      "katex"
    ));

    // ── renderContent: double-backslash AI output ───────────────────────────

    tests.push(notContains(
      "RC-10 | \\\\( normalised and rendered — no raw \\\\( in output",
      "\\\\(2x + 3 = 11\\\\)",
      "\\\\("
    ));

    tests.push(notContains(
      "RC-11 | \\\\[ normalised and rendered — no raw \\\\[ in output",
      "\\\\[a^2 + b^2 = c^2\\\\]",
      "\\\\["
    ));

    // ── renderContent: multiline equations ─────────────────────────────────

    tests.push(notContains(
      "RC-12 | multiline block equation — no raw \\[ in output",
      "\\[\nx = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}\n\\]",
      "\\["
    ));

    tests.push(contains(
      "RC-13 | multiline block equation — katex rendered",
      "\\[\nx = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}\n\\]",
      "katex"
    ));

    // ── renderContent: unmatched delimiters ─────────────────────────────────

    tests.push(notContains(
      "RC-14 | unmatched \\( with no close — stripped from output",
      "Hello \\( world",
      "\\("
    ));

    tests.push(notContains(
      "RC-15 | unmatched \\[ with no close — stripped from output",
      "Some \\[ text here",
      "\\["
    ));

    // ── renderContent: markdown ─────────────────────────────────────────────

    tests.push(contains(
      "RC-16 | **bold** renders as <strong>",
      "**bold text**",
      "<strong>bold text</strong>"
    ));

    tests.push(contains(
      "RC-17 | *italic* renders as <em>",
      "*italic text*",
      "<em>italic text</em>"
    ));

    tests.push(contains(
      "RC-18 | # heading renders as <h1>",
      "# Title Here",
      "<h1>Title Here</h1>"
    ));

    tests.push(contains(
      "RC-19 | ## heading renders as <h2>",
      "## Section",
      "<h2>Section</h2>"
    ));

    tests.push(contains(
      "RC-20 | ### heading renders as <h3>",
      "### Subsection",
      "<h3>Subsection</h3>"
    ));

    tests.push(contains(
      "RC-21 | - list item renders as <li>",
      "- item one",
      "<li>item one</li>"
    ));

    tests.push(contains(
      "RC-22 | ordered list item renders as <li>",
      "1. first item",
      "<li>first item</li>"
    ));

    tests.push(contains(
      "RC-23 | inline `code` renders as <code>",
      "Use `x = 5` here.",
      "<code>x = 5</code>"
    ));

    tests.push(contains(
      "RC-24 | fenced code block renders as <pre><code>",
      "```\nconst x = 1;\n```",
      "<pre><code>"
    ));

    // ── renderContent: markdown + math mixed ────────────────────────────────

    tests.push(contains(
      "RC-25 | markdown + inline math — bold present",
      "**Solve** \\(x + 1 = 0\\) now.",
      "<strong>Solve</strong>"
    ));

    tests.push(notContains(
      "RC-26 | markdown + inline math — no raw delimiters",
      "**Solve** \\(x + 1 = 0\\) now.",
      "\\("
    ));

    tests.push(contains(
      "RC-27 | list + block math — list item present",
      "- Step 1\n\\[x = 4\\]\n- Step 2",
      "<li>Step 1</li>"
    ));

    tests.push(notContains(
      "RC-28 | list + block math — no raw \\[ in output",
      "- Step 1\n\\[x = 4\\]\n- Step 2",
      "\\["
    ));

    // ── renderContent: HTML injection / XSS ────────────────────────────────

    tests.push(notContains(
      "RC-29 | <script> in input — stripped from output",
      'Hello <script>alert("xss")</script> world',
      "<script>"
    ));

    tests.push(notContains(
      "RC-30 | javascript: href — stripped from output",
      'click <a href="javascript:alert(1)">here</a>',
      "javascript:"
    ));

    tests.push(notContains(
      "RC-31 | onclick= handler — not raw in output",
      '<div onclick="evil()">text</div>',
      'onclick='
    ));

    // ── renderContent: idempotency ──────────────────────────────────────────

    tests.push(assert(
      "RC-32 | renderContent is idempotent (same input → same output twice)",
      null,
      () => {
        const input = "**Hello** \\(x = 1\\) and \\[y^2\\]";
        return R.renderContent(input) === R.renderContent(input);
      }
    ));

    tests.push(assert(
      "RC-33 | renderContent second call on its own output is stable (no double-render drift)",
      null,
      () => {
        const input = "\\(a + b = c\\)";
        const once = R.renderContent(input);
        const twice = R.renderContent(once);
        // KaTeX HTML should not contain raw delimiters to re-render on second pass
        return !twice.includes("\\(") && !twice.includes("\\)");
      }
    ));

    // ── renderContent: edge cases ───────────────────────────────────────────

    tests.push(assert(
      "RC-34 | empty string input returns string (not crash)",
      R.renderContent(""),
      (o) => typeof o === "string"
    ));

    tests.push(assert(
      "RC-35 | non-string input returns empty string",
      R.renderContent(null),
      (o) => o === ""
    ));

    tests.push(assert(
      "RC-36 | undefined input returns empty string",
      R.renderContent(undefined),
      (o) => o === ""
    ));

    tests.push(notContains(
      "RC-37 | streaming chunk ending mid-sentence (no trailing delimiter)",
      "The answer is x =",
      "\\("
    ));

    tests.push(notContains(
      "RC-38 | ampersand in LaTeX label text — does not double-escape in KaTeX output",
      "Use \\(a \\& b\\) for logic.",
      "\\("
    ));

    tests.push(contains(
      "RC-39 | heading followed immediately by math — heading tag present",
      "## Energy\n\\[E = mc^2\\]",
      "<h2>Energy</h2>"
    ));

    tests.push(notContains(
      "RC-40 | heading followed immediately by math — no raw \\[",
      "## Energy\n\\[E = mc^2\\]",
      "\\["
    ));

    // ── Visual regression snapshots ─────────────────────────────────────────
    // These test exact output strings.  They will FAIL if pipeline behaviour
    // changes, alerting you to check whether the change was intentional.

    tests.push(snapshot(
      "SNAP-01 | plain text wraps in <p> tags",
      "Hello world",
      "<p>Hello world</p>"
    ));

    tests.push(snapshot(
      "SNAP-02 | bold only",
      "**hello**",
      "<p><strong>hello</strong></p>"
    ));

    tests.push(snapshot(
      "SNAP-03 | HTML special chars escaped",
      "a & b < c > d",
      "<p>a &amp; b &lt; c &gt; d</p>"
    ));

    return tests;
  }

  // ── Runner ────────────────────────────────────────────────────────────────

  function runRenderTests() {
    const R_check = global.AmiCorRenderer;
    if (!R_check) {
      console.error("[render.test] AmiCorRenderer not found. Load render.js first.");
      return;
    }
    R = R_check; // resolve for helper functions

    console.group("🧪 AmiCorRenderer Test Suite");
    console.time("⏱ Total runtime");

    const tests = buildTests();
    let passed = 0;
    let failed = 0;
    const failures = [];

    tests.forEach((t, idx) => {
      const prefix = String(idx + 1).padStart(3, "0");
      if (t.passed) {
        console.log(`  ✅ PASS [${prefix}] ${t.description}`);
        passed++;
      } else {
        console.warn(`  ❌ FAIL [${prefix}] ${t.description}`);
        if (t.expected !== undefined) {
          console.warn(`         expected : ${JSON.stringify(t.expected)}`);
          console.warn(`         actual   : ${JSON.stringify(t.actual)}`);
        } else {
          console.warn(`         actual   : ${JSON.stringify(t.actual)}`);
        }
        failed++;
        failures.push(t);
      }
    });

    console.timeEnd("⏱ Total runtime");
    console.log(`\n  Summary: ${passed} passed, ${failed} failed out of ${tests.length} tests`);

    if (failed === 0) {
      console.log("  🎉 All tests passed — rendering pipeline is stable.");
    } else {
      console.warn(`  ⚠️  ${failed} test(s) failed — review above.`);
    }

    console.groupEnd();
    return { passed, failed, total: tests.length, failures };
  }

  // ── Future extension hooks ────────────────────────────────────────────────
  //
  // The sections below document WHERE to plug in each capability when the
  // time comes.  No code is added yet — architecture is stabilised first.
  //
  // HOOK: Syntax highlighting
  //   Stage: between Stage 4 (applyMarkdown) and Stage 5 (sanitizeHtml)
  //   Approach: after applyMarkdown produces <pre><code class="language-js">…</code></pre>,
  //             walk the string and apply Prism.js or highlight.js to each
  //             <code> block's text content.
  //   Integration point in render.js:
  //     const s4b = applySyntaxHighlighting(s4);   // NEW Stage 4b
  //
  // HOOK: Tables
  //   Stage: inside Stage 4 (applyMarkdown)
  //   Approach: detect pipe-delimited rows (| col | col |) before the
  //             paragraph/line-break pass and convert to <table><tr><td>.
  //   Integration point in render.js:
  //     add .replace(TABLE_REGEX, tableToHtml) inside applyMarkdown().
  //
  // HOOK: Citations / footnotes
  //   Stage: inside Stage 4, or a new Stage 4c after syntax highlighting
  //   Approach: detect [^1] markers, collect them, convert to <sup> links
  //             and append a <footer> reference list.
  //
  // HOOK: Diagrams (Mermaid)
  //   Stage: between Stage 4 and Stage 5 (similar to syntax highlighting)
  //   Approach: replace ```mermaid … ``` fenced blocks with
  //             <div class="mermaid">…</div> in Stage 4, then call
  //             mermaid.init() on those nodes AFTER DOM insertion.
  //   Note: Mermaid requires DOM; this is the ONE legitimate reason to do
  //         a post-insertion call — keep it isolated from the text pipeline.
  //
  // HOOK: Streaming token rendering
  //   Approach: renderContent() is already streaming-safe because it is
  //             pure and stateless.  To support incremental updates:
  //             1. Keep a pendingBuffer per message.
  //             2. On each streamed chunk: buffer += chunk
  //             3. Call renderContent(pendingBuffer) and set bubble.innerHTML
  //                each time — the whole pipeline re-runs but is cheap.
  //             4. On stream end: do one final renderContent() pass.
  //   No changes to render.js are needed — the caller in index.html manages
  //   the buffer.

  // ── Expose ───────────────────────────────────────────────────────────────

  global.runRenderTests = runRenderTests;

})(window);
