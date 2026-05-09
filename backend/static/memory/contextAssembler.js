"use strict";

const { estimateTokens } = require("./memoryRanker");
const { compressMemories } = require("./memoryCompressor");

function createContextAssembler(options) {
  var config = Object.assign(
    {
      retriever: null,
      maxTokens: 1200,
      compressionOptions: {},
    },
    options || {}
  );

  async function assemble(input) {
    var criteria = input || {};
    if (!config.retriever || typeof config.retriever.retrieve !== "function") {
      throw new Error("Context assembler requires a memory retriever");
    }

    var retrieval = await config.retriever.retrieve(criteria.query || "", Object.assign({}, criteria, {
      limit: criteria.limit || config.maxEntries || 50,
    }));
    var compressed = compressMemories(retrieval.items, Object.assign({}, config.compressionOptions, {
      maxTokens: criteria.maxTokens || config.maxTokens,
      query: criteria.query || "",
    }));

    var memoryBlocks = compressed.retained.map(function (memory) {
      return {
        id: memory.id,
        type: memory.type,
        content: memory.content,
        source: memory.source,
        timestamp: memory.timestamp,
        importance: memory.importance,
      };
    });

    var summaryBlock = compressed.summary ? {
      id: "summary-" + Date.now(),
      type: "summary",
      content: compressed.summary.summary,
      source: "memoryCompressor",
      timestamp: Date.now(),
      importance: 0.4,
    } : null;

    var blocks = memoryBlocks.slice();
    if (summaryBlock) {
      blocks.push(summaryBlock);
    }

    var assembled = blocks.map(function (block) {
      return "[" + block.type + "] " + (typeof block.content === "string" ? block.content : JSON.stringify(block.content || {}));
    }).join("\n");

    var tokensEstimated = estimateTokens(assembled);
    var maxTokens = criteria.maxTokens || config.maxTokens;
    var overflowed = tokensEstimated > maxTokens;
    if (overflowed) {
      compressed.truncated = true;
    }

    return {
      query: criteria.query || "",
      tokensEstimated: tokensEstimated,
      maxTokens: maxTokens,
      truncated: compressed.truncated || overflowed,
      retrieval: retrieval,
      compressed: compressed,
      context: assembled,
      blocks: blocks,
    };
  }

  return {
    config: config,
    assemble: assemble,
  };
}

module.exports = { createContextAssembler: createContextAssembler };