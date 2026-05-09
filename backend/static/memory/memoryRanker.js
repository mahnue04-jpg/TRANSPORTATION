"use strict";

function normalizeText(value) {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value).toLowerCase();
    } catch (_) {
      return String(value).toLowerCase();
    }
  }
  return String(value).toLowerCase();
}

function estimateTokens(value) {
  return Math.max(1, Math.ceil(String(value || "").length / 4));
}

function similarityScore(query, content, embedding, embeddingProvider) {
  var normalizedQuery = normalizeText(query);
  var normalizedContent = normalizeText(typeof content === "string" ? content : JSON.stringify(content || {}));
  var lexicalScore = 0;
  if (normalizedQuery && normalizedContent.indexOf(normalizedQuery) !== -1) {
    lexicalScore += 0.6;
  }
  var queryTerms = normalizedQuery.split(/\s+/).filter(Boolean);
  queryTerms.forEach(function (term) {
    if (normalizedContent.indexOf(term) !== -1) {
      lexicalScore += 0.08;
    }
  });
  if (embeddingProvider && embedding && query) {
    lexicalScore += 0.2 * cosineSimilarity(embeddingProvider.embedSync(query), embedding);
  }
  return Math.min(1, lexicalScore);
}

function cosineSimilarity(left, right) {
  if (!Array.isArray(left) || !Array.isArray(right) || left.length === 0 || right.length === 0) {
    return 0;
  }
  var length = Math.min(left.length, right.length);
  var dot = 0;
  var leftMagnitude = 0;
  var rightMagnitude = 0;
  for (var index = 0; index < length; index++) {
    dot += left[index] * right[index];
    leftMagnitude += left[index] * left[index];
    rightMagnitude += right[index] * right[index];
  }
  if (leftMagnitude === 0 || rightMagnitude === 0) {
    return 0;
  }
  return dot / (Math.sqrt(leftMagnitude) * Math.sqrt(rightMagnitude));
}

function scoreMemory(memory, query, options) {
  var config = options || {};
  var ageMs = Math.max(0, Date.now() - (memory.timestamp || Date.now()));
  var recencyHalfLifeMs = config.recencyHalfLifeMs || 1000 * 60 * 60 * 24;
  var recencyScore = Math.exp(-ageMs / recencyHalfLifeMs);
  var relevanceScore = similarityScore(query, memory.content, memory.embedding, config.embeddingProvider);
  var frequencyScore = Math.min(1, (memory.metadata && Number(memory.metadata.frequency) ? Number(memory.metadata.frequency) : 1) / (config.frequencyScale || 5));
  var importanceScore = typeof memory.importance === "number" ? memory.importance : 0.5;
  var total = (config.weights && config.weights.recency || 0.25) * recencyScore +
    (config.weights && config.weights.relevance || 0.45) * relevanceScore +
    (config.weights && config.weights.frequency || 0.15) * frequencyScore +
    (config.weights && config.weights.importance || 0.15) * importanceScore;

  return {
    recency: recencyScore,
    relevance: relevanceScore,
    frequency: frequencyScore,
    importance: importanceScore,
    total: total,
  };
}

function rankMemories(memories, query, options) {
  return (memories || []).map(function (memory) {
    var score = scoreMemory(memory, query, options);
    return Object.assign({}, memory, { score: score });
  }).sort(function (left, right) {
    return right.score.total - left.score.total || right.timestamp - left.timestamp;
  });
}

function dedupeMemories(memories) {
  var seen = new Set();
  var result = [];
  (memories || []).forEach(function (memory) {
    var fingerprint = [memory.type, normalizeText(memory.content), normalizeText(memory.source), normalizeText(memory.sessionId)].join("|");
    if (seen.has(fingerprint)) {
      return;
    }
    seen.add(fingerprint);
    result.push(memory);
  });
  return result;
}

function filterStaleMemories(memories, options) {
  var config = options || {};
  var ttlMs = config.ttlMs || 1000 * 60 * 60 * 24 * 7;
  var cutoff = Date.now() - ttlMs;
  return (memories || []).filter(function (memory) {
    return (memory.timestamp || 0) >= cutoff;
  });
}

module.exports = {
  estimateTokens: estimateTokens,
  similarityScore: similarityScore,
  scoreMemory: scoreMemory,
  rankMemories: rankMemories,
  dedupeMemories: dedupeMemories,
  filterStaleMemories: filterStaleMemories,
  cosineSimilarity: cosineSimilarity,
};