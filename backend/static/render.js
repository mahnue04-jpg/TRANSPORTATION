/**
 * render.js — Amicor content rendering pipeline
 *
 * Pure input → output module.  No DOM access.  No side effects.
 * Exposed as window.AmiCorRenderer for use in index.html.
 *
 * Pipeline (renderContent):
 *   Stage 0 – normalizeDelimiters   collapse \\( / \\[ emitted by AI models
 *   Stage 1 – extractMathBlocks     pull out every LaTeX span, render with KaTeX,
 *                                   replace with %%MATH_n%% placeholders
 *   Stage 2 – stripStrayDelimiters  remove unmatched \( \) \[ \] that Stage 1 missed
 *   Stage 3 – escapeHtml            HTML-encode the remaining plain text (XSS guard)
 *   Stage 4 – applyMarkdown         convert markdown syntax to safe HTML tags
 *   Stage 5 – sanitizeHtml          strip any surviving dangerous patterns
 *   Stage 6 – restoreMathBlocks     splice pre-rendered KaTeX HTML back in
 *
 * Internal helper (renderMathToString):
 *   Calls katex.renderToString().  On failure: logs + returns escaped plain text,
 *   never re-inserts raw delimiters.
 *
 * All stage functions are exposed under AmiCorRenderer._stages for unit testing.
 */

(function (global) {
  "use strict";

  // ─────────────────────────────────────────────────────────────────────────
  // Stage 0 — Normalise delimiters
  // AI models sometimes emit \\( (double backslash + paren) instead of \(.
  // Collapse to single-backslash so all subsequent stages see uniform input.
  // ─────────────────────────────────────────────────────────────────────────
  function normalizeDelimiters(text) {
    return text
      .replace(/\\\\\[/g, "\\[")
      .replace(/\\\\\]/g, "\\]")
      .replace(/\\\\\(/g, "\\(")
      .replace(/\\\\\)/g, "\\)");
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Internal utility — HTML-escape a plain-text string
  // Used by renderMathToString fallback path.
  // ─────────────────────────────────────────────────────────────────────────
  function _escapePlain(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // ─────────────────────────────────────────────────────────────────────────
  // KaTeX helper — called inside Stage 1 only
  // Returns rendered KaTeX HTML string, or plain-escaped text on any failure.
  // Never re-inserts raw delimiter characters into the output.
  // ─────────────────────────────────────────────────────────────────────────
  function renderMathToString(inner, displayMode) {
    const trimmed = inner.trim();

    if (!global.katex) {
      // Library not loaded — plain text fallback (should not happen after page load)
      console.warn("[AmiCorRenderer] katex not loaded; math shown as plain text:", trimmed.slice(0, 60));
      return _escapePlain(trimmed);
    }

    try {
      return global.katex.renderToString(trimmed, {
        displayMode,
        throwOnError: false,   // let KaTeX emit its own error span, not throw
        output: "html",
      });
    } catch (err) {
      // renderToString with throwOnError:false should not reach here, but guard anyway
      console.warn("[AmiCorRenderer] KaTeX parse error:", err.message, "| expression:", trimmed.slice(0, 80));
      return _escapePlain(trimmed);
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Stage 1 — Extract and render every LaTeX block
  //
  // Four delimiter styles:
  //   \[ … \]   display (block)
  //   \( … \)   inline
  //   $$ … $$   display (block)
  //   $ … $     inline  (single-line only — avoids false positives on prices)
  //
  // The FULL match including delimiters is consumed and replaced by a token.
  // Returns { safe: string, mathBlocks: string[] }
  // ─────────────────────────────────────────────────────────────────────────
  function extractMathBlocks(text) {
    const mathBlocks = [];

    function extract(inner, displayMode) {
      const i = mathBlocks.length;
      mathBlocks.push(renderMathToString(inner, displayMode));
      return `%%MATH_${i}%%`;
    }

    const safe = text
      .replace(/\\\[([\s\S]*?)\\\]/g,  (_, inner) => extract(inner, true))   // \[ … \]
      .replace(/\\\(([\s\S]*?)\\\)/g,  (_, inner) => extract(inner, false))  // \( … \)
      .replace(/\$\$([\s\S]*?)\$\$/g,  (_, inner) => extract(inner, true))   // $$ … $$
      .replace(/\$([^\n$]+?)\$/g,       (_, inner) => extract(inner, false)); // $ … $

    return { safe, mathBlocks };
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Stage 2 — Strip stray unmatched delimiters
  // Any \(, \), \[, \] that Stage 1 did not consume (because they had no
  // matching close) are removed here so they never reach HTML output.
  // ─────────────────────────────────────────────────────────────────────────
  function stripStrayDelimiters(text) {
    return text.replace(/\\[\[\]()]/g, "");
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Stage 3 — HTML-escape non-math plain text
  // Only & < > are encoded; quote-encoding is not needed because this text
  // is inserted via innerHTML (not into attribute values).
  // ─────────────────────────────────────────────────────────────────────────
  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Stage 4 — Markdown → HTML
  // All LaTeX is already absent (replaced by %%MATH_n%% tokens) so the
  // \n → <br> pass can never split a multiline equation.
  // ─────────────────────────────────────────────────────────────────────────
  function applyMarkdown(text) {
    let html = text
      // fenced code blocks first (preserves newlines inside them)
      .replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>")
      // inline code
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      // headings
      .replace(/^### (.+)/gm, "<h3>$1</h3>")
      .replace(/^## (.+)/gm,  "<h2>$1</h2>")
      .replace(/^# (.+)/gm,   "<h1>$1</h1>")
      // bold / italic
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      // unordered + ordered list items
      .replace(/^[\s]*[-*] (.+)/gm, "<li>$1</li>")
      .replace(/^\d+\. (.+)/gm, "<li>$1</li>")
      // wrap consecutive <li> runs in <ul>
      .replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, (m) => `<ul>${m}</ul>`)
      // paragraphs and line breaks
      .replace(/\n\n/g, "</p><p>")
      .replace(/\n/g, "<br>");

    return `<p>${html}</p>`;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Stage 5 — Sanitise HTML (defence-in-depth)
  // The pipeline produces controlled markup; this is a final guard against
  // any edge-case injection that might have slipped through.
  // Strips: <script …>, javascript: hrefs, inline on* handlers.
  // KaTeX HTML and markdown tags are not affected.
  // ─────────────────────────────────────────────────────────────────────────
  function sanitizeHtml(html) {
    return html
      .replace(/<script[\s\S]*?<\/script>/gi, "")
      .replace(/javascript\s*:/gi, "")
      .replace(/\bon\w+\s*=/gi, "data-blocked=");
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Stage 6 — Restore pre-rendered KaTeX HTML at placeholder positions
  // This is the only point where trusted KaTeX HTML is inserted; all other
  // content was HTML-escaped in Stage 3.
  // ─────────────────────────────────────────────────────────────────────────
  function restoreMathBlocks(html, mathBlocks) {
    return html.replace(/%%MATH_(\d+)%%/g, (_, i) => mathBlocks[parseInt(i, 10)]);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Main entry point — renderContent(rawText) → finalHtml
  //
  // Deterministic, one-way, no DOM access, no secondary render pass.
  // Safe to call multiple times with the same input (pure function).
  // ─────────────────────────────────────────────────────────────────────────
  function renderContent(rawText) {
    if (typeof rawText !== "string") {
      console.warn("[AmiCorRenderer] renderContent received non-string:", typeof rawText);
      return "";
    }

    const s0 = normalizeDelimiters(rawText);                      // Stage 0
    const { safe: s1, mathBlocks } = extractMathBlocks(s0);       // Stage 1
    const s2 = stripStrayDelimiters(s1);                           // Stage 2
    const s3 = escapeHtml(s2);                                     // Stage 3
    const s4 = applyMarkdown(s3);                                  // Stage 4
    const s5 = sanitizeHtml(s4);                                   // Stage 5
    const s6 = restoreMathBlocks(s5, mathBlocks);                  // Stage 6

    return s6;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Public API
  // ─────────────────────────────────────────────────────────────────────────
  global.AmiCorRenderer = {
    renderContent,

    // Individual stages exposed for unit testing.
    // Prefix _ signals "internal — not part of the stable public contract".
    _stages: {
      normalizeDelimiters,
      extractMathBlocks,
      stripStrayDelimiters,
      escapeHtml,
      applyMarkdown,
      sanitizeHtml,
      restoreMathBlocks,
      renderMathToString,
    },
  };

})(window);
