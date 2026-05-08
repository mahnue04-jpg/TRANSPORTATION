/**
 * orchestrator.js — AmiCorOrchestrator
 *
 * Runtime coordination layer for Amicor.
 * Manages message lifecycle, stream sessions, cancellation, retries,
 * history, events, and performance instrumentation.
 *
 * RESPONSIBILITIES (this module only):
 *   - Message state machine
 *   - Conversation history (append-only, immutable snapshots)
 *   - Event bus (onMessageStart, onChunk, onRender, onComplete,
 *                onCancel, onError, onRetry)
 *   - Cancellation (AbortController wiring, session cleanup)
 *   - Retry scheduling (exponential back-off, max attempts)
 *   - Performance instrumentation (latency, throughput, DOM patches)
 *   - Deterministic replay from saved chunk lists
 *
 * NON-RESPONSIBILITIES (delegated to other layers):
 *   - DOM manipulation           → caller / index.html
 *   - Markdown / LaTeX parsing   → AmiCorRenderer
 *   - Safe-boundary detection    → AmiCorStreamingEngine
 *   - Business / tool logic      → future modules
 *
 * ── Architecture ──────────────────────────────────────────────────────────
 *
 *   AI model
 *   → AmiCorOrchestrator        (this file)
 *   → AmiCorStreamingEngine     (streaming.js)
 *   → AmiCorRenderer            (render.js)
 *   → DOM element (bubble)
 *
 * ── Usage ─────────────────────────────────────────────────────────────────
 *
 *   const conv = AmiCorOrchestrator.createConversation({ id: "c1" });
 *
 *   conv.on("onChunk",    ({ chunk }) => console.log("token:", chunk));
 *   conv.on("onComplete", ({ message }) => console.log("done:", message.id));
 *
 *   const session = conv.startMessage({
 *     role:    "assistant",
 *     element: bubbleDomElement,
 *   });
 *
 *   // Feed chunks from SSE / fetch stream:
 *   session.push(chunk);
 *   session.finish();
 *
 *   // Cancel mid-stream:
 *   session.cancel();
 *
 *   // Replay saved chunks:
 *   conv.replay(messageId, chunkArray, element);
 *
 *   // Test suite:
 *   orchestratorTests();
 *
 * ── Future extension hooks ────────────────────────────────────────────────
 *
 * FUTURE: Tool execution
 *   session.emitToolCall({ name, args })      → fires onToolCall event
 *   session.emitToolResult({ name, result })  → fires onToolResult event
 *
 * FUTURE: Voice pipeline
 *   conv.on("onSafeChunk", ({ text }) => tts.speak(text))
 *   streaming engine safe-chunk callback wired here.
 *
 * FUTURE: Memory system
 *   conv.on("onComplete", ({ message }) => memoryStore.save(message))
 *
 * FUTURE: Agent routing
 *   AmiCorOrchestrator.createAgentConversation({ agentId, routerFn })
 *
 * FUTURE: Multi-model inference
 *   session.setModel("gpt-4o")   → updates metadata on message record
 *
 * FUTURE: Background tasks
 *   AmiCorOrchestrator.scheduleBackgroundTask({ fn, onResult })
 */

(function (global) {
  "use strict";

  // ─────────────────────────────────────────────────────────────────────────
  // Constants
  // ─────────────────────────────────────────────────────────────────────────

  var MSG_STATES = {
    IDLE:       "idle",
    QUEUED:     "queued",
    STREAMING:  "streaming",
    RENDERING:  "rendering",
    COMPLETED:  "completed",
    CANCELLED:  "cancelled",
    FAILED:     "failed",
    RETRYING:   "retrying",
  };

  var EVENTS = [
    "onMessageStart",
    "onChunk",
    "onRender",
    "onComplete",
    "onCancel",
    "onError",
    "onRetry",
    // Future hooks (registered but not yet emitted internally)
    "onToolCall",
    "onToolResult",
    "onSafeChunk",
    "onAgentEvent",
  ];

  var DEFAULT_RETRY_MAX      = 3;
  var DEFAULT_RETRY_BASE_MS  = 500;  // base back-off delay
  var DEFAULT_MIN_RENDER_MS  = 50;

  // ─────────────────────────────────────────────────────────────────────────
  // Utilities
  // ─────────────────────────────────────────────────────────────────────────

  var _idCounter = 0;
  function _uid(prefix) {
    _idCounter++;
    return (prefix || "msg") + "-" + Date.now() + "-" + _idCounter;
  }

  function _now() { return Date.now(); }
  function _perf() { return (typeof performance !== "undefined") ? performance.now() : _now(); }

  function _freeze(obj) {
    if (Object.freeze) return Object.freeze(obj);
    return obj;
  }

  /** Shallow-clone a plain object. */
  function _clone(obj) {
    var out = {};
    for (var k in obj) {
      if (Object.prototype.hasOwnProperty.call(obj, k)) out[k] = obj[k];
    }
    return out;
  }

  /** Estimate bytes used by a string (UTF-16 approximation). */
  function _estimateStringBytes(str) {
    return str ? str.length * 2 : 0;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // EventBus
  // Mini event emitter for one conversation.
  // ─────────────────────────────────────────────────────────────────────────

  function EventBus() {
    this._handlers = {};
  }

  EventBus.prototype.on = function (event, fn) {
    if (!this._handlers[event]) this._handlers[event] = [];
    this._handlers[event].push(fn);
    return this; // chainable
  };

  EventBus.prototype.off = function (event, fn) {
    if (!this._handlers[event]) return;
    this._handlers[event] = this._handlers[event].filter(function (h) {
      return h !== fn;
    });
  };

  EventBus.prototype.emit = function (event, payload) {
    var handlers = this._handlers[event];
    if (!handlers || handlers.length === 0) return;
    for (var i = 0; i < handlers.length; i++) {
      try { handlers[i](payload); } catch (e) {
        console.warn("[AmiCorOrchestrator] Event handler threw on '" + event + "':", e);
      }
    }
  };

  EventBus.prototype.destroy = function () {
    this._handlers = {};
  };

  // ─────────────────────────────────────────────────────────────────────────
  // MessageRecord
  // Append-only snapshot of one message.  Frozen fields cannot be mutated
  // from outside; internal tracking uses _mutable.
  // ─────────────────────────────────────────────────────────────────────────

  function MessageRecord(opts) {
    this.id            = opts.id || _uid("msg");
    this.role          = opts.role || "assistant";
    this.conversationId = opts.conversationId || "";
    this.rawText       = "";
    this.renderedHtml  = "";
    this.streamingState = MSG_STATES.IDLE;
    this.errorState    = null;
    this.retryCount    = 0;
    this.tokenCount    = 0;
    this.renderStats   = null;

    this.timestamps = {
      created:   _now(),
      started:   null,
      firstChunk: null,
      completed: null,
      cancelled: null,
      failed:    null,
    };

    // Saved chunks for replay
    this._chunks = [];
  }

  MessageRecord.prototype.snapshot = function () {
    return _freeze({
      id:             this.id,
      role:           this.role,
      conversationId: this.conversationId,
      rawText:        this.rawText,
      renderedHtml:   this.renderedHtml,
      streamingState: this.streamingState,
      errorState:     this.errorState,
      retryCount:     this.retryCount,
      tokenCount:     this.tokenCount,
      renderStats:    this.renderStats ? _clone(this.renderStats) : null,
      timestamps:     _clone(this.timestamps),
      chunkCount:     this._chunks.length,
    });
  };

  // ─────────────────────────────────────────────────────────────────────────
  // StreamingSession
  // Wraps one AmiCorStreamingEngine session + one MessageRecord.
  // Created by Conversation.startMessage(); returned to caller.
  // ─────────────────────────────────────────────────────────────────────────

  function StreamingSession(opts) {
    // opts: { message, element, bus, onFinish, minRenderMs }
    this._message    = opts.message;
    this._element    = opts.element;   // DOM element (treated opaquely)
    this._bus        = opts.bus;
    this._onFinish   = opts.onFinish;  // callback → Conversation internal
    this._destroyed  = false;
    this._abortCtrl  = (typeof AbortController !== "undefined") ? new AbortController() : null;

    this._streamSession = null;

    // Initialise streaming engine session if element + engine available
    if (this._element && global.AmiCorStreamingEngine) {
      this._streamSession = global.AmiCorStreamingEngine.create(this._element, {
        minRenderInterval: opts.minRenderMs || DEFAULT_MIN_RENDER_MS,
        showCursor: true,
        onRender: this._onRenderCallback.bind(this),
        onError:  this._onEngineError.bind(this),
      });
    }

    // Performance tracking
    this._perf = {
      streamStartTime:     null,
      firstChunkTime:      null,
      lastChunkTime:       null,
      renderCount:         0,
      totalRenderLatency:  0,
      domPatchCount:       0,
      chunkCount:          0,
      byteCount:           0,
    };
  }

  StreamingSession.prototype._onRenderCallback = function (html, engineStats) {
    var msg = this._message;
    msg.renderedHtml = html;

    if (engineStats) {
      this._perf.renderCount    = engineStats.renderCount    || this._perf.renderCount;
      this._perf.domPatchCount  = engineStats.domPatchCount  || this._perf.domPatchCount;
    }

    this._bus.emit("onRender", {
      messageId: msg.id,
      html:      html,
      stats:     engineStats,
    });
  };

  StreamingSession.prototype._onEngineError = function (err) {
    console.warn("[AmiCorOrchestrator] Engine render error:", err);
    this._bus.emit("onError", {
      messageId: this._message.id,
      error:     err,
      phase:     "render",
    });
  };

  /**
   * push(chunk)
   * Feed one text token from the AI stream.
   */
  StreamingSession.prototype.push = function (chunk) {
    if (this._destroyed) return;

    var msg  = this._message;
    var perf = this._perf;

    perf.chunkCount++;
    if (typeof chunk === "string") {
      perf.byteCount += chunk.length;
      msg.rawText    += chunk;
      msg.tokenCount++;

      if (!perf.firstChunkTime) {
        perf.firstChunkTime       = _perf();
        msg.timestamps.firstChunk = _now();
      }
      perf.lastChunkTime = _perf();

      msg._chunks.push(chunk);
    }

    // Update message state
    if (msg.streamingState === MSG_STATES.STREAMING) {
      // no-op, already streaming
    }

    if (this._streamSession) {
      this._streamSession.appendChunk(chunk || "");
    }

    this._bus.emit("onChunk", {
      messageId: msg.id,
      chunk:     chunk,
      rawText:   msg.rawText,
    });
  };

  /**
   * finish()
   * Signal stream end.  Flushes final render and marks message completed.
   */
  StreamingSession.prototype.finish = function () {
    if (this._destroyed) return;

    var msg  = this._message;
    var perf = this._perf;

    msg.streamingState    = MSG_STATES.RENDERING;
    msg.timestamps.completed = _now();

    if (this._streamSession) {
      this._streamSession.flushFinalRender();
      var engineStats = this._streamSession.getStats();
      msg.renderStats = {
        chunkCount:         engineStats.chunkCount,
        renderCount:        engineStats.renderCount,
        domPatchCount:      engineStats.domPatchCount,
        totalRenderMs:      engineStats.totalRenderDurationMs,
        peakBufferSize:     engineStats.peakBufferSize,
        byteCount:          engineStats.byteCount,
        streamDurationMs:   perf.lastChunkTime
          ? (perf.lastChunkTime - (perf.streamStartTime || perf.firstChunkTime || perf.lastChunkTime))
          : 0,
        firstChunkLatencyMs: perf.firstChunkTime && perf.streamStartTime
          ? (perf.firstChunkTime - perf.streamStartTime)
          : null,
        tokenThroughput:    perf.lastChunkTime && perf.streamStartTime && perf.streamStartTime !== perf.lastChunkTime
          ? (msg.tokenCount / ((perf.lastChunkTime - perf.streamStartTime) / 1000)).toFixed(1)
          : null,
        estimatedMemoryBytes: _estimateStringBytes(msg.rawText) + _estimateStringBytes(msg.renderedHtml),
      };
    }

    msg.streamingState = MSG_STATES.COMPLETED;
    this._destroyed    = true;

    this._bus.emit("onComplete", {
      messageId: msg.id,
      message:   msg.snapshot(),
    });

    if (this._onFinish) this._onFinish(msg, "completed");
  };

  /**
   * cancel()
   * Abort the stream mid-flight.  Preserves partial render.
   */
  StreamingSession.prototype.cancel = function () {
    if (this._destroyed) return;

    var msg = this._message;
    msg.streamingState    = MSG_STATES.CANCELLED;
    msg.timestamps.cancelled = _now();

    if (this._abortCtrl) {
      try { this._abortCtrl.abort(); } catch (e) { /* ignore */ }
    }

    if (this._streamSession) {
      // Flush whatever was safely buffered so far
      try { this._streamSession.flushFinalRender(); } catch (e) { /* ignore */ }
      try { this._streamSession.destroy(); } catch (e) { /* ignore */ }
    }

    this._destroyed = true;

    this._bus.emit("onCancel", {
      messageId: msg.id,
      message:   msg.snapshot(),
    });

    if (this._onFinish) this._onFinish(msg, "cancelled");
  };

  /**
   * getAbortSignal()
   * Returns the AbortSignal for use with fetch() calls.
   */
  StreamingSession.prototype.getAbortSignal = function () {
    return this._abortCtrl ? this._abortCtrl.signal : null;
  };

  /**
   * getStreamSession()
   * Returns the underlying AmiCorStreamingEngine session (for advanced use).
   */
  StreamingSession.prototype.getStreamSession = function () {
    return this._streamSession;
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Conversation
  // Manages a sequence of messages, history, retries, and events.
  // ─────────────────────────────────────────────────────────────────────────

  function Conversation(opts) {
    this.id         = opts.id || _uid("conv");
    this._bus       = new EventBus();
    this._history   = [];       // append-only MessageRecord array
    this._active    = null;     // current StreamingSession or null
    this._destroyed = false;

    this._retryConfig = {
      maxAttempts: (opts.retryMax != null) ? opts.retryMax : DEFAULT_RETRY_MAX,
      baseDelayMs: (opts.retryBaseMs != null) ? opts.retryBaseMs : DEFAULT_RETRY_BASE_MS,
    };

    this._stats = {
      totalMessages:   0,
      totalTokens:     0,
      totalCancels:    0,
      totalRetries:    0,
      totalErrors:     0,
      totalRenderMs:   0,
    };
  }

  /**
   * on(event, fn) / off(event, fn)
   * Subscribe/unsubscribe from conversation events.
   */
  Conversation.prototype.on = function (event, fn) {
    this._bus.on(event, fn);
    return this;
  };

  Conversation.prototype.off = function (event, fn) {
    this._bus.off(event, fn);
    return this;
  };

  /**
   * startMessage(opts) → StreamingSession
   *
   * opts:
   *   role        {string}   default "assistant"
   *   element     {Element}  DOM element for this bubble (opaque handle)
   *   id          {string}   optional explicit message id
   *   minRenderMs {number}   throttle interval for streaming engine
   */
  Conversation.prototype.startMessage = function (opts) {
    if (this._destroyed) throw new Error("[AmiCorOrchestrator] Conversation is destroyed.");

    opts = opts || {};

    // If an active session exists (shouldn't normally happen), cancel it first
    if (this._active && !this._active._destroyed) {
      console.warn("[AmiCorOrchestrator] startMessage() called while session active — cancelling previous.");
      this._active.cancel();
    }

    var msg = new MessageRecord({
      id:             opts.id || _uid("msg"),
      role:           opts.role || "assistant",
      conversationId: this.id,
    });
    msg.streamingState    = MSG_STATES.STREAMING;
    msg.timestamps.started = _now();

    this._history.push(msg);
    this._stats.totalMessages++;

    var self = this;
    var session = new StreamingSession({
      message:     msg,
      element:     opts.element || null,
      bus:         this._bus,
      minRenderMs: opts.minRenderMs,
      onFinish: function (finishedMsg, outcome) {
        self._active = null;
        if (outcome === "completed") {
          self._stats.totalTokens    += finishedMsg.tokenCount;
          if (finishedMsg.renderStats) {
            self._stats.totalRenderMs += (finishedMsg.renderStats.totalRenderMs || 0);
          }
        } else if (outcome === "cancelled") {
          self._stats.totalCancels++;
        }
      },
    });

    session._perf.streamStartTime = _perf();

    this._active = session;

    this._bus.emit("onMessageStart", {
      messageId: msg.id,
      role:      msg.role,
    });

    return session;
  };

  /**
   * retry(messageId, element, opts) → StreamingSession
   *
   * Re-opens a new streaming session for a previously failed/cancelled message.
   * Resets rawText and renderedHtml; preserves id and history position.
   */
  Conversation.prototype.retry = function (messageId, element, opts) {
    if (this._destroyed) throw new Error("[AmiCorOrchestrator] Conversation is destroyed.");

    var msg = this._findMessage(messageId);
    if (!msg) throw new Error("[AmiCorOrchestrator] Message not found: " + messageId);

    if (msg.retryCount >= this._retryConfig.maxAttempts) {
      var err = new Error("[AmiCorOrchestrator] Max retries (" + this._retryConfig.maxAttempts + ") reached for message " + messageId);
      this._bus.emit("onError", { messageId: messageId, error: err, phase: "retry" });
      throw err;
    }

    // Reset message state for retry
    msg.rawText        = "";
    msg.renderedHtml   = "";
    msg.errorState     = null;
    msg.streamingState = MSG_STATES.RETRYING;
    msg.retryCount++;
    msg._chunks        = [];

    this._stats.totalRetries++;

    this._bus.emit("onRetry", {
      messageId:  msg.id,
      retryCount: msg.retryCount,
    });

    // Re-start session immediately (caller handles back-off timer if needed)
    var session = this.startMessage(Object.assign({ id: msg.id, element: element }, opts || {}));
    return session;
  };

  /**
   * replay(messageId, chunks, element, opts) → Promise
   *
   * Deterministic replay: feed saved chunks at a controlled interval.
   * Returns a Promise that resolves with the final message snapshot.
   */
  Conversation.prototype.replay = function (messageId, chunks, element, opts) {
    if (this._destroyed) return Promise.reject(new Error("Conversation destroyed"));
    opts = opts || {};

    var chunkDelayMs = opts.chunkDelayMs != null ? opts.chunkDelayMs : 0;
    var self         = this;

    // Find existing record or create a new one for replay
    var msg = this._findMessage(messageId);
    if (msg) {
      // Reset for replay
      msg.rawText        = "";
      msg.renderedHtml   = "";
      msg.streamingState = MSG_STATES.STREAMING;
      msg._chunks        = [];
    }

    var session = self.startMessage({ id: messageId, element: element, minRenderMs: opts.minRenderMs });

    return new Promise(function (resolve, reject) {
      var i = 0;

      function sendNext() {
        if (session._destroyed) { reject(new Error("Session cancelled during replay")); return; }
        if (i >= chunks.length) {
          session.finish();
          var finishedMsg = self._findMessage(messageId);
          resolve(finishedMsg ? finishedMsg.snapshot() : null);
          return;
        }
        session.push(chunks[i]);
        i++;
        if (chunkDelayMs > 0) {
          setTimeout(sendNext, chunkDelayMs);
        } else {
          sendNext();
        }
      }
      sendNext();
    });
  };

  /**
   * markFailed(messageId, error)
   * Mark a message as failed (e.g. network error).
   */
  Conversation.prototype.markFailed = function (messageId, error) {
    var msg = this._findMessage(messageId);
    if (!msg) return;

    msg.streamingState  = MSG_STATES.FAILED;
    msg.errorState      = error ? String(error) : "unknown";
    msg.timestamps.failed = _now();

    this._stats.totalErrors++;

    if (this._active && this._active._message.id === messageId) {
      try { this._active._streamSession && this._active._streamSession.destroy(); } catch (e) { /* ignore */ }
      this._active = null;
    }

    this._bus.emit("onError", {
      messageId: messageId,
      error:     error,
      phase:     "stream",
    });
  };

  /**
   * cancelActive()
   * Cancel the currently active streaming session (if any).
   */
  Conversation.prototype.cancelActive = function () {
    if (this._active && !this._active._destroyed) {
      this._active.cancel();
    }
  };

  /**
   * getHistory() → array of frozen snapshots
   * Returns an immutable copy of all message records.
   */
  Conversation.prototype.getHistory = function () {
    return this._history.map(function (m) { return m.snapshot(); });
  };

  /**
   * getMessage(id) → frozen snapshot or null
   */
  Conversation.prototype.getMessage = function (id) {
    var msg = this._findMessage(id);
    return msg ? msg.snapshot() : null;
  };

  /**
   * getStats() → performance snapshot
   */
  Conversation.prototype.getStats = function () {
    return _clone(this._stats);
  };

  /** Internal: find mutable record by id. */
  Conversation.prototype._findMessage = function (id) {
    for (var i = 0; i < this._history.length; i++) {
      if (this._history[i].id === id) return this._history[i];
    }
    return null;
  };

  /**
   * reset()
   * Clear all history and stats.  Cancels active session first.
   * Bus listeners are preserved.
   */
  Conversation.prototype.reset = function () {
    this.cancelActive();
    this._history  = [];
    this._active   = null;
    this._stats    = {
      totalMessages: 0,
      totalTokens:   0,
      totalCancels:  0,
      totalRetries:  0,
      totalErrors:   0,
      totalRenderMs: 0,
    };
  };

  /**
   * destroy()
   * Permanently destroys this conversation.  All sessions, bus, and history
   * are cleared.  After destroy() all methods throw or are no-ops.
   */
  Conversation.prototype.destroy = function () {
    this.cancelActive();
    this._bus.destroy();
    this._history  = [];
    this._active   = null;
    this._destroyed = true;
  };

  // ─────────────────────────────────────────────────────────────────────────
  // AmiCorOrchestrator — public factory
  // ─────────────────────────────────────────────────────────────────────────

  var _conversations = {};

  var AmiCorOrchestrator = {

    /**
     * createConversation(opts) → Conversation
     * opts: { id, retryMax, retryBaseMs }
     */
    createConversation: function (opts) {
      opts = opts || {};
      var conv = new Conversation(opts);
      _conversations[conv.id] = conv;
      return conv;
    },

    /**
     * getConversation(id) → Conversation or undefined
     */
    getConversation: function (id) {
      return _conversations[id];
    },

    /**
     * destroyConversation(id)
     * Destroy and remove a conversation.
     */
    destroyConversation: function (id) {
      var conv = _conversations[id];
      if (conv) {
        conv.destroy();
        delete _conversations[id];
      }
    },

    /**
     * resetConversation(id)
     * Clear history/stats of an existing conversation without destroying it.
     */
    resetConversation: function (id) {
      var conv = _conversations[id];
      if (conv) conv.reset();
    },

    /**
     * listConversations() → array of ids
     */
    listConversations: function () {
      return Object.keys(_conversations);
    },

    // Expose state constants
    MSG_STATES: MSG_STATES,
    EVENTS:     EVENTS,

    // Internal classes exposed for testing
    _Conversation:    Conversation,
    _StreamingSession: StreamingSession,
    _MessageRecord:   MessageRecord,
    _EventBus:        EventBus,
  };

  global.AmiCorOrchestrator = AmiCorOrchestrator;

})(window);
