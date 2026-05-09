/**
 * mockLargeChunkTool — Emits very large chunks to test backpressure
 * Usage: { chunkCount: 5, bytesPerChunk: 100000 }
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  global.AmiCorMockTools.largeChunkTool = {
    name: "mock-large-chunk",
    description: "Emits very large chunks to stress-test streaming",
    schema: {
      chunkCount: { type: "number", required: true, min: 1, max: 100 },
      bytesPerChunk: { type: "number", required: false, min: 1024, max: 10485760 } // 1KB - 10MB
    },
    permissions: [],
    timeout: 30000,
    retryable: true,
    execute: function (args, ctx) {
      var count = args.chunkCount || 5;
      var bytes = args.bytesPerChunk || 100000;
      var emitted = 0;
      var totalBytes = 0;

      return new Promise(function (resolve) {
        function emitNext() {
          if (emitted >= count) {
            resolve({ largeChunksEmitted: emitted, totalBytes: totalBytes });
            return;
          }

          // Create large chunk (but as reasonable string to avoid memory bloat)
          var chunkData = "chunk-" + emitted + ":";
          var remaining = Math.max(0, bytes - chunkData.length);
          var padding = new Array(Math.min(remaining, 1000)).fill("X").join("");
          var chunk = chunkData + padding + ":" + emitted;

          ctx.emitChunk(chunk);
          emitted++;
          totalBytes += chunk.length;

          setImmediate(emitNext);
        }
        emitNext();
      });
    }
  };
})(typeof global !== "undefined" ? global : globalThis);
