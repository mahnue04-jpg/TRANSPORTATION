/* ─── runtime/streaming.js ───────────────────────────────────────────────
 * Tool-chunk streaming context (different from render streaming.js).
 * Buffers and validates chunks emitted during tool execution.
 * Exposed on window._AmiCorRT.streaming
 * ─────────────────────────────────────────────────────────────────────── */
(function (global) {
  "use strict";
  var ns = global._AmiCorRT = global._AmiCorRT || {};
  var errors = ns.errors || {};
  var ToolExecutionError = errors.ToolExecutionError || Error;

  var DEFAULT_MAX_CHUNKS = 10000;
  var DEFAULT_MAX_BYTES  = 50 * 1024 * 1024; /* 50 MB */

  function StreamingContext(opts) {
    opts = opts || {};
    this._maxChunks   = opts.maxChunks   || DEFAULT_MAX_CHUNKS;
    this._maxBytes    = opts.maxChunkBytes || DEFAULT_MAX_BYTES;
    this._chunks      = [];
    this._totalBytes  = 0;
    this._count       = 0;
    this.onChunk      = opts.onChunk || null;
  }

  StreamingContext.prototype.push = function (chunk) {
    if (this._count >= this._maxChunks) {
      throw new ToolExecutionError(
        "Chunk limit exceeded: max " + this._maxChunks + " chunks"
      );
    }
    var str   = typeof chunk === "string" ? chunk : JSON.stringify(chunk);
    var bytes = str.length * 2; /* rough UTF-16 estimate */
    if (this._totalBytes + bytes > this._maxBytes) {
      throw new ToolExecutionError(
        "Chunk byte limit exceeded: max " + this._maxBytes + " bytes"
      );
    }
    this._chunks.push(chunk);
    this._totalBytes += bytes;
    this._count++;
    if (typeof this.onChunk === "function") {
      try { this.onChunk(chunk); } catch (e) { /* isolate consumer errors */ }
    }
  };

  StreamingContext.prototype.getChunks = function () {
    return this._chunks.slice();
  };

  StreamingContext.prototype.getCount = function () {
    return this._count;
  };

  StreamingContext.prototype.getBytes = function () {
    return this._totalBytes;
  };

  StreamingContext.prototype.reset = function () {
    this._chunks     = [];
    this._totalBytes = 0;
    this._count      = 0;
  };

  ns.streaming = {
    StreamingContext    : StreamingContext,
    DEFAULT_MAX_CHUNKS  : DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_BYTES   : DEFAULT_MAX_BYTES
  };
})(window);
