"use strict";

const { createSecurityError } = require("./pathSanitizer");

function ensureWithinLimit(size, maxSize, label) {
  if (maxSize === undefined || maxSize === null) {
    return true;
  }
  if (size > maxSize) {
    throw createSecurityError("size-limit-exceeded", (label || "Value") + " exceeds the configured size limit", {
      size: size,
      maxSize: maxSize,
    });
  }
  return true;
}

function estimateSize(value) {
  if (value === null || value === undefined) {
    return 0;
  }
  if (Buffer.isBuffer(value)) {
    return value.length;
  }
  return Buffer.byteLength(String(value));
}

function truncateText(text, maxBytes) {
  const source = String(text || "");
  if (!maxBytes || Buffer.byteLength(source) <= maxBytes) {
    return source;
  }
  let end = Math.max(0, Math.min(source.length, maxBytes));
  while (end > 0 && Buffer.byteLength(source.slice(0, end)) > maxBytes) {
    end -= 1;
  }
  return source.slice(0, end);
}

module.exports = {
  ensureWithinLimit: ensureWithinLimit,
  estimateSize: estimateSize,
  truncateText: truncateText,
};