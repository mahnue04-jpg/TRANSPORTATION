"use strict";

const fs = require("fs/promises");
const path = require("path");

const { sanitizeSandboxPath, estimateSize } = require("../toolSecurity");
const { paginate } = require("./baseAdapter");

async function walkFiles(rootDir, allowlist) {
  const entries = [];
  async function visit(currentPath) {
    const dirents = await fs.readdir(currentPath, { withFileTypes: true });
    for (const dirent of dirents) {
      const nextPath = path.join(currentPath, dirent.name);
      if (dirent.isDirectory()) {
        await visit(nextPath);
        continue;
      }
      if (allowlist && allowlist.length > 0 && allowlist.indexOf(path.extname(nextPath).toLowerCase()) === -1) {
        continue;
      }
      entries.push(nextPath);
    }
  }
  await visit(rootDir);
  return entries;
}

function createSearchAdapter(options) {
  const config = Object.assign(
    {
      rootDir: path.resolve(process.cwd(), "backend/static/.real-tool-sandbox"),
      allowedExtensions: [".txt", ".md", ".json"],
      indexer: null,
    },
    options || {}
  );

  async function search(args, ctx) {
    const rootDir = sanitizeSandboxPath(config.rootDir, ".", { allowRoot: true });
    const query = String(args.query || "").trim();
    if (!query) {
      return {
        query: query,
        results: [],
        total: 0,
        page: 1,
        pageSize: Number(args.pageSize) || 10,
        indexMode: config.indexer ? "pluggable" : "filesystem-scan",
        semanticReady: true,
      };
    }

    if (config.indexer && typeof config.indexer.searchIndex === "function") {
      const index = config.indexer.buildIndex ? await config.indexer.buildIndex(rootDir, args, ctx) : null;
      const indexedResults = await config.indexer.searchIndex(query, index, args, ctx);
      const pageData = paginate(indexedResults || [], args.page, args.pageSize);
      return Object.assign({}, pageData, {
        query: query,
        indexMode: "pluggable",
        semanticReady: true,
      });
    }

    const files = await walkFiles(rootDir, config.allowedExtensions);
    const results = [];
    const lowerQuery = query.toLowerCase();

    for (const filePath of files) {
      const text = await fs.readFile(filePath, "utf8").catch(function () {
        return "";
      });
      const lowerText = text.toLowerCase();
      const score = (lowerText.match(new RegExp(lowerQuery.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) || []).length;
      if (score > 0) {
        const excerptIndex = lowerText.indexOf(lowerQuery);
        const excerpt = excerptIndex >= 0 ? text.slice(Math.max(0, excerptIndex - 40), excerptIndex + query.length + 80) : text.slice(0, 120);
        results.push({
          path: filePath,
          score: score,
          excerpt: excerpt,
          bytes: estimateSize(text),
        });
      }
    }

    results.sort(function (a, b) {
      return b.score - a.score || a.path.localeCompare(b.path);
    });

    const pageData = paginate(results, args.page, args.pageSize);
    if (ctx && typeof ctx.emitChunk === "function") {
      pageData.items.forEach(function (item) {
        ctx.emitChunk(item);
      });
    }

    return Object.assign({}, pageData, {
      query: query,
      indexMode: "filesystem-scan",
      semanticReady: true,
    });
  }

  return {
    config: config,
    search: search,
  };
}

module.exports = { createSearchAdapter: createSearchAdapter };