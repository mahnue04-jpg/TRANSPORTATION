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

  function _escapeAttr(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function decodeBasicEntities(text) {
    return String(text || "")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
      .replace(/&quot;/gi, '"')
      .replace(/&#39;/gi, "'")
      .replace(/&amp;/gi, "&");
  }

  function normalizeWhitespace(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function sanitizeUrl(url) {
    try {
      const parsed = new URL(String(url || "").trim());
      return /^https?:$/i.test(parsed.protocol) ? parsed.toString() : "";
    } catch (_) {
      return "";
    }
  }

  function compactUrlLabel(url) {
    const safeUrl = sanitizeUrl(url);
    if (!safeUrl) return "Link";
    try {
      const parsed = new URL(safeUrl);
      const host = parsed.hostname.replace(/^www\./i, "");
      const path = (parsed.pathname || "").replace(/\/$/, "");
      const label = `${host}${path && path !== "/" ? path : ""}`;
      return label.length > 52 ? `${label.slice(0, 49)}...` : label;
    } catch (_) {
      return safeUrl.length > 52 ? `${safeUrl.slice(0, 49)}...` : safeUrl;
    }
  }

  function buildSafeAnchor(url, label) {
    const safeUrl = sanitizeUrl(url);
    const safeLabel = normalizeWhitespace(label || compactUrlLabel(url) || "Open link");
    if (!safeUrl) return _escapePlain(safeLabel);
    return `<a class="safe-link" href="${_escapeAttr(safeUrl)}" target="_blank" rel="noreferrer noopener"><span class="safe-link-label">${_escapePlain(safeLabel)}</span></a>`;
  }

  function stripHtmlTags(text) {
    return String(text || "")
      .replace(/<!\[CDATA\[|\]\]>/gi, " ")
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/?[a-z][^>]*>/gi, " ")
      .replace(/&lt;br\s*\/?&gt;/gi, "\n")
      .replace(/&lt;\/?[a-z][^&]*&gt;/gi, " ");
  }

  function normalizeFeed(text) {
    return decodeBasicEntities(String(text || ""))
      .replace(/<!\[CDATA\[|\]\]>/gi, " ")
      .replace(/\r\n?/g, "\n")
      .replace(/[\u0000-\u001F\u007F]/g, (m) => (m === "\n" || m === "\t" ? m : " "));
  }

  function sanitizeHTML(text) {
    return String(text || "")
      .replace(/&lt;\/?a\b[^&]*&gt;/gi, " ")
      .replace(/<\/?a\b[^>]*>/gi, " ")
      .replace(/\b(?:target|href|style|font)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, " ")
      .replace(/&(?:quot|#34);\s*>/gi, " ")
      .replace(/(?:^|\s)(?:TARGET|HREF|STYLE|FONT)\s*=\s*[^\s]+/g, " ")
      .replace(/&lt;[^&]*&gt;/gi, " ")
      .replace(/<[^>]*>/g, " ")
      .replace(/\b(?:rss|atom|feedburner|xmlns|media:)\b\s*[:=]?\s*[^\s]*/gi, " ")
      .replace(/&(?:nbsp|amp);/gi, " ")
      .replace(/[ \t]+/g, " ")
      .replace(/\s+\n/g, "\n")
      .trim();
  }

  function extractMetadata(rawItem) {
    const item = rawItem || {};
    const source = normalizeWhitespace(stripHtmlTags(item.source || ""));
    const publishedAt = normalizeWhitespace(stripHtmlTags(item.publishedAt || ""));
    const category = normalizeWhitespace(stripHtmlTags(item.category || ""));
    const safeUrl = sanitizeUrl(item.url || "");
    const summary = normalizeWhitespace(stripHtmlTags(item.summary || ""));
    const title = normalizeWhitespace(stripHtmlTags(item.title || ""));
    return {
      title,
      source: source || "Source",
      summary: summary || "Open the full article for details.",
      url: safeUrl,
      publishedAt: publishedAt || "",
      category: category || "",
    };
  }

  function renderStructuredCard(item) {
    const data = extractMetadata(item);
    if (!data.url || !data.title) return "";
    const metaBits = [data.source, data.publishedAt].filter(Boolean);
    const metaLine = metaBits.length ? metaBits.join(" • ") : data.source;
    const categoryChip = data.category ? `<span class="news-result-category">${_escapePlain(data.category)}</span>` : "";
    return (
      `<article class="news-result-card">` +
        `<div class="news-result-headline">${_escapePlain(data.title)}</div>` +
        `<div class="news-result-source">${_escapePlain(metaLine)}${categoryChip}</div>` +
        `<div class="news-result-summary">${_escapePlain(data.summary)}</div>` +
        `<div class="news-result-link-row">${buildSafeAnchor(data.url, "Open Article")}</div>` +
      `</article>`
    );
  }

  function sanitizeProviderText(text) {
    let out = String(text || "");

    out = out.replace(/&lt;a\s+href=(?:"|')((?:https?:\/\/)[^"']+)(?:"|')[^&]*&gt;([\s\S]*?)&lt;\/a&gt;/gi,
      (_, href, label) => `[${normalizeWhitespace(stripHtmlTags(decodeBasicEntities(label)) || compactUrlLabel(href))}](${href})`);

    out = out.replace(/<a\s+[^>]*href=(?:"|')((?:https?:\/\/)[^"']+)(?:"|')[^>]*>([\s\S]*?)<\/a>/gi,
      (_, href, label) => `[${normalizeWhitespace(stripHtmlTags(label) || compactUrlLabel(href))}](${href})`);

    out = out
      .replace(/<!\[CDATA\[|\]\]>/gi, " ")
      .replace(/\b(?:target|href|style|font)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, " ")
      .replace(/(?:^|\s)(?:TARGET|HREF|STYLE|FONT)\s*=\s*[^\s]+/g, " ")
      .replace(/&lt;\/?font\b[^&]*&gt;/gi, " ")
      .replace(/<\/?font\b[^>]*>/gi, " ")
      .replace(/&lt;\/?(?:span|div|p|section|article|small)\b[^&]*&gt;/gi, " ")
      .replace(/<\/?(?:span|div|p|section|article|small)\b[^>]*>/gi, " ")
      .replace(/&lt;\/?[a-z][^&]*&gt;/gi, " ")
      .replace(/<\/?[a-z][^>]*>/gi, " ")
      .replace(/[\u0000-\u001F\u007F]/g, (m) => (m === "\n" || m === "\t" ? m : " "));

    return out.replace(/[ \t]+/g, " ").replace(/\s+\n/g, "\n").trim();
  }

  function promotePlainUrlsToMarkdown(text) {
    return String(text || "").replace(/https?:\/\/[^\s<]+/g, (match, offset, whole) => {
      if (whole.slice(Math.max(0, offset - 2), offset) === "](") return match;
      const clean = match.replace(/[.,!?;:]+$/g, "");
      const trailing = match.slice(clean.length);
      const safeUrl = sanitizeUrl(clean);
      if (!safeUrl) return match;
      return `[${compactUrlLabel(safeUrl)}](${safeUrl})${trailing}`;
    });
  }

  function looksLikeNewsPayload(text) {
    const normalized = decodeBasicEntities(String(text || ""));
    const urlCount = (normalized.match(/https?:\/\//gi) || []).length;
    return urlCount >= 2 && /(search results for|latest news|news\.google\.com|headlines|top stories|rss)/i.test(normalized);
  }

  function parseStructuredNews(text) {
    const normalized = sanitizeHTML(normalizeFeed(text));
    const items = [];
    const itemPattern = /(\d+)\.\s*([\s\S]*?)(https?:\/\/[^\s]+)([\s\S]*?)(?=(?:\s+\d+\.\s)|$)/gi;
    let match;

    while ((match = itemPattern.exec(normalized)) !== null) {
      const rawLead = normalizeWhitespace(stripHtmlTags(match[2]).replace(/\s*[:\-–—]\s*$/, ""));
      const url = sanitizeUrl(match[3]);
      const rawTail = normalizeWhitespace(stripHtmlTags(match[4]).replace(/^[:\-–—\s]+/, ""));
      if (!url || !rawLead) continue;

      let headline = rawLead;
      let source = rawTail || "";
      let publishedAt = "";
      let category = "";

      const splitLead = rawLead.match(/^(.*?)\s+[-–—]\s+(.+)$/);
      if (splitLead) {
        headline = normalizeWhitespace(splitLead[1]);
        source = source || normalizeWhitespace(splitLead[2]);
      }

      const datedTail = rawTail.match(/(.+?)\s+[•\-|]\s+((?:\w+\s+\d{1,2},\s*\d{4})|(?:\d{4}-\d{2}-\d{2})|(?:\d{1,2}\/\d{1,2}\/\d{2,4}))/i);
      if (datedTail) {
        source = normalizeWhitespace(datedTail[1]);
        publishedAt = normalizeWhitespace(datedTail[2]);
      }

      const categoryTail = rawTail.match(/\b(category|topic)\s*[:\-]\s*([^\-•|]+)/i);
      if (categoryTail) {
        category = normalizeWhitespace(categoryTail[2]);
      }

      if (!source) {
        try {
          source = new URL(url).hostname.replace(/^www\./i, "");
        } catch (_) {
          source = "Source";
        }
      }

      items.push({
        title: headline,
        source,
        summary: rawTail && rawTail !== source ? rawTail : `Open the full article for details.`,
        url,
        publishedAt,
        category,
      });
    }

    return items;
  }

  function renderStructuredNews(text) {
    if (!looksLikeNewsPayload(text)) return null;
    const items = parseStructuredNews(text);
    if (!items.length) return null;

    const headingMatch = decodeBasicEntities(String(text || "")).match(/search results for ['"]?([^:'"]+)['"]?\s*:/i);
    const heading = headingMatch ? normalizeWhitespace(stripHtmlTags(headingMatch[1])) : "News results";

    const cards = items.map((item) => renderStructuredCard(item)).filter(Boolean).join("");
    if (!cards) return null;

    return `<section class="news-result-list"><div class="news-result-kicker">${_escapePlain(heading)}</div>${cards}</section>`;
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
  // Stage 0.5 — SANITIZE MEMORY MARKERS AND ORCHESTRATION LABELS
  // 
  // Remove internal markers that should NEVER appear in user-visible output:
  // - [MEMORY_CONTEXT] … [/MEMORY_CONTEXT] blocks
  // - short_term_memory, long_term_memory, orchestration labels
  // - internal system tags and hidden instructions
  // 
  // This is critical: memory architecture and internal markers are
  // implementation details and must never leak to the user interface.
  // ─────────────────────────────────────────────────────────────────────────
  function stripInternalMarkers(text) {
    let sanitized = String(text || "");
    
    // Remove [MEMORY_CONTEXT] … [/MEMORY_CONTEXT] blocks entirely
    sanitized = sanitized.replace(/\[MEMORY_CONTEXT\]([\s\S]*?)\[\/MEMORY_CONTEXT\]/g, " ");
    
    // Remove other memory architecture markers
    sanitized = sanitized.replace(/\[MEMORY_(?:START|END|BLOCK)\]/gi, " ");
    sanitized = sanitized.replace(/\[\/MEMORY_(?:START|END|BLOCK)\]/gi, " ");
    
    // Remove internal memory layer references (never show "short_term_memory" or "long_term_memory" to user)
    sanitized = sanitized.replace(/\bshort[_\-\s]?term[_\-\s]?memory\b/gi, " ");
    sanitized = sanitized.replace(/\blong[_\-\s]?term[_\-\s]?memory\b/gi, " ");
    
    // Remove orchestration metadata labels that leaked from routing layer
    sanitized = sanitized.replace(/\b(?:routed|route_intent|intent_classification|capability_selection)\s*[:=]?\s*[^\s,]*/gi, " ");
    sanitized = sanitized.replace(/\[(?:ROUTED|INTENT|ROUTE|CAPABILITY)\]/gi, " ");
    
    // Remove hidden system instructions and internal tags
    sanitized = sanitized.replace(/\[SYSTEM_(?:INSTRUCTION|TAG|BLOCK|METADATA)\]/gi, " ");
    sanitized = sanitized.replace(/<!--[\s\S]*?-->/g, " ");
    
    // Clean up excessive whitespace that resulted from removal
    sanitized = sanitized.replace(/\s+/g, " ").trim();
    
    return sanitized;
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
      // markdown links
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, href) => buildSafeAnchor(href, decodeBasicEntities(label)))
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
      .replace(/\bon\w+\s*=/gi, "data-blocked=")
      .replace(/\sstyle\s*=\s*(?:"[^"]*"|'[^']*')/gi, "");
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

    const s0_sanitized = stripInternalMarkers(rawText);              // Stage 0.5 - Remove memory markers
    const s0 = normalizeDelimiters(s0_sanitized);                   // Stage 0 - Normalize delimiters
    const { safe: s1, mathBlocks } = extractMathBlocks(s0);         // Stage 1
    const s2 = stripStrayDelimiters(s1);                             // Stage 2
    const structuredNews = renderStructuredNews(s2);
    if (structuredNews) {
      return structuredNews;
    }
    const s2b = promotePlainUrlsToMarkdown(sanitizeProviderText(s2));
    const s3 = escapeHtml(s2b);                                      // Stage 3
    const s4 = applyMarkdown(s3);                                    // Stage 4
    const s5 = sanitizeHtml(s4);                                     // Stage 5
    const s6 = restoreMathBlocks(s5, mathBlocks);                    // Stage 6

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
      stripInternalMarkers,          // Stage 0.5 - Remove memory markers
      normalizeDelimiters,
      extractMathBlocks,
      stripStrayDelimiters,
      sanitizeProviderText,
      normalizeFeed,
      sanitizeHTML,
      extractMetadata,
      renderStructuredCard,
      promotePlainUrlsToMarkdown,
      escapeHtml,
      applyMarkdown,
      sanitizeHtml,
      restoreMathBlocks,
      renderMathToString,
      renderStructuredNews,
    },
  };

})(window);
