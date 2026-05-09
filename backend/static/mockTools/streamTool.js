/**
 * mockStreamTool — Emits multiple chunks rapidly
 * Usage: { chunkCount: 10, chunkSize: 100, delayBetweenChunks: 5 }
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  global.AmiCorMockTools.streamTool = {
    name: "mock-stream",
    description: "Rapidly emits chunks to test streaming infrastructure",
    schema: {
      chunkCount: { type: "number", required: true, min: 1, max: 1000 },
      chunkSize: { type: "number", required: false, min: 1, max: 10000 },
      delayBetweenChunks: { type: "number", required: false, min: 0, max: 100 }
    },
    permissions: [],
    timeout: 10000,
    retryable: true,
    execute: function (args, ctx) {
      var count = args.chunkCount || 10;
      var size = args.chunkSize || 100;
      var delay = args.delayBetweenChunks || 1;
      var emitted = 0;

      return new Promise(function (resolve) {
        function emitNext() {
          if (emitted >= count) {
            resolve({ chunksEmitted: emitted, totalBytes: emitted * size });
            return;
          }
          var chunk = "chunk-" + emitted + ":" + new Array(size).fill("x").join("");
          ctx.emitChunk(chunk);
          emitted++;
          if (delay > 0) {
            setTimeout(emitNext, delay);
          } else {
            setImmediate(emitNext);
          }
        }
        emitNext();
      });
    }
  };
})(typeof global !== "undefined" ? global : globalThis);
