"use strict";

const fs = require("fs/promises");
const path = require("path");

const { sanitizeSandboxPath, ensurePermissions, estimateSize, truncateText } = require("../toolSecurity");
const { createToolError, chunkText } = require("./baseAdapter");

function createDocumentAdapter(options) {
  const config = Object.assign(
    {
      rootDir: path.resolve(process.cwd(), "backend/static/.real-tool-sandbox"),
      allowedExtensions: [".txt", ".md", ".json"],
      maxSummaryChars: 600,
      chunkSize: 1024,
    },
    options || {}
  );

  async function readText(args, ctx) {
    ensurePermissions(["document:read"], ctx && ctx.permissions, "documentTool");
    const targetPath = sanitizeSandboxPath(config.rootDir, args.path, { allowRoot: false });
    const ext = path.extname(targetPath).toLowerCase();
    if (config.allowedExtensions.indexOf(ext) === -1) {
      throw createToolError("extension-not-supported", "Document type is not supported", {
        extension: ext,
        allowedExtensions: config.allowedExtensions,
      });
    }
    const content = await fs.readFile(targetPath, "utf8");
    if (ctx && typeof ctx.emitChunk === "function") {
      chunkText(content, args.chunkSize || config.chunkSize).forEach(function (chunk) {
        ctx.emitChunk(chunk);
      });
    }
    return { path: targetPath, format: ext.replace(/^\./, ""), bytes: estimateSize(content), text: content };
  }

  async function summarizeText(args, ctx) {
    ensurePermissions(["document:read"], ctx && ctx.permissions, "documentTool");
    const source = args.text !== undefined ? String(args.text) : String(await readText({ path: args.path }, ctx).then(function (result) { return result.text; }));
    const maxSentences = Math.max(1, Number(args.maxSentences) || 3);
    const sentences = source
      .split(/(?<=[.!?])\s+|\n+/)
      .map(function (sentence) { return sentence.trim(); })
      .filter(Boolean)
      .slice(0, maxSentences);
    const summary = truncateText(sentences.join(" "), args.maxChars || config.maxSummaryChars);
    return { summary: summary, sentencesUsed: sentences.length, characters: summary.length };
  }

  async function extractMetadata(args, ctx) {
    ensurePermissions(["document:read"], ctx && ctx.permissions, "documentTool");
    const text = args.text !== undefined ? String(args.text) : String(await readText({ path: args.path }, ctx).then(function (result) { return result.text; }));
    const metadata = {
      bytes: estimateSize(text),
      characters: text.length,
      lines: text.split(/\r?\n/).length,
      words: text.trim() ? text.trim().split(/\s+/).length : 0,
    };

    if (args.path) {
      const ext = path.extname(args.path).toLowerCase();
      metadata.extension = ext;
      metadata.format = ext.replace(/^\./, "");
    }

    if ((metadata.extension || "") === ".json") {
      try {
        const parsed = JSON.parse(text);
        metadata.jsonType = Array.isArray(parsed) ? "array" : typeof parsed;
        metadata.jsonKeys = parsed && typeof parsed === "object" ? Object.keys(parsed).length : 0;
      } catch (error) {
        metadata.jsonError = error.message;
      }
    }

    return metadata;
  }

  async function chunkDocument(args, ctx) {
    ensurePermissions(["document:read"], ctx && ctx.permissions, "documentTool");
    const text = args.text !== undefined ? String(args.text) : String(await readText({ path: args.path }, ctx).then(function (result) { return result.text; }));
    const chunks = chunkText(text, args.chunkSize || config.chunkSize);
    if (ctx && typeof ctx.emitChunk === "function") {
      chunks.forEach(function (chunk) {
        ctx.emitChunk(chunk);
      });
    }
    return { chunks: chunks, chunkCount: chunks.length, bytes: estimateSize(text) };
  }

  return {
    config: config,
    readText: readText,
    summarizeText: summarizeText,
    extractMetadata: extractMetadata,
    chunkDocument: chunkDocument,
  };
}

module.exports = { createDocumentAdapter: createDocumentAdapter };