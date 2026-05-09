"use strict";

function createStreamingRenderer(options) {
  var config = Object.assign(
    {
      flushIntervalMs: 16,
      maxBufferedTokens: 5000,
    },
    options || {}
  );

  var tokenBuffer = [];
  var renderedText = "";
  var interrupted = false;
  var timer = null;

  function flush(force) {
    if (interrupted) {
      return renderedText;
    }

    if (!force && tokenBuffer.length === 0) {
      return renderedText;
    }

    renderedText += tokenBuffer.join("");
    tokenBuffer = [];
    if (typeof config.onRender === "function") {
      config.onRender(renderedText);
    }
    return renderedText;
  }

  function scheduleFlush() {
    if (timer) {
      return;
    }
    timer = setTimeout(function () {
      timer = null;
      flush(false);
    }, config.flushIntervalMs);
  }

  function appendToken(token) {
    if (interrupted) {
      return renderedText;
    }
    if (tokenBuffer.length >= config.maxBufferedTokens) {
      flush(true);
    }
    tokenBuffer.push(String(token || ""));
    scheduleFlush();
    return renderedText;
  }

  function interrupt() {
    interrupted = true;
    tokenBuffer = [];
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    return renderedText;
  }

  function resume() {
    interrupted = false;
  }

  function finalize() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    return flush(true);
  }

  function reset() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    tokenBuffer = [];
    renderedText = "";
    interrupted = false;
  }

  function snapshot() {
    return {
      renderedText: renderedText,
      bufferedTokens: tokenBuffer.length,
      interrupted: interrupted,
    };
  }

  return {
    appendToken: appendToken,
    flush: flush,
    finalize: finalize,
    interrupt: interrupt,
    resume: resume,
    reset: reset,
    snapshot: snapshot,
  };
}

module.exports = {
  createStreamingRenderer: createStreamingRenderer,
};
