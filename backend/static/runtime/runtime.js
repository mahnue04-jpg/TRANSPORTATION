/* ─── runtime/runtime.js ─────────────────────────────────────────────────
 * Core ToolRuntime: orchestrates registry, lifecycle, events, permissions,
 * metrics, streaming, backpressure, cancellation, retry, and shutdown.
 * Exposed on window._AmiCorRT.runtime
 * ─────────────────────────────────────────────────────────────────────── */
(function (global) {
  "use strict";
  var ns = global._AmiCorRT = global._AmiCorRT || {};

  /* ── Module references ── */
  var Errors      = ns.errors      || {};
  var LC          = ns.lifecycle   || {};
  var Ev          = ns.events      || {};
  var Reg         = ns.registry    || {};
  var Val         = ns.validator   || {};
  var Perm        = ns.permissions || {};
  var Met         = ns.metrics     || {};
  var Str         = ns.streaming   || {};

  var ToolValidationError = Errors.ToolValidationError || Error;
  var ToolTimeoutError    = Errors.ToolTimeoutError    || Error;
  var ToolPermissionError = Errors.ToolPermissionError || Error;
  var ToolCancelledError  = Errors.ToolCancelledError  || Error;
  var ToolExecutionError  = Errors.ToolExecutionError  || Error;
  var isRetryable         = Errors.isRetryable         || function () { return false; };

  var STATES     = LC.STATES     || {};
  var isTerminal = LC.isTerminal || function () { return false; };
  var assertTx   = LC.assertTransition || function () {};

  var EventBus   = Ev.EventBus   || function () {};
  var HookSet    = Ev.HookSet    || function () {};
  var ToolRegistry    = Reg.ToolRegistry    || function () {};
  var validateSchema  = Val.validateSchema  || function () {};
  var StreamingContext = Str.StreamingContext || function () {};
  var Metrics    = Met.Metrics   || function () {};

  /* ── UUID generator with fallback ── */
  function genUUID() {
    if (global.crypto && typeof global.crypto.randomUUID === "function") {
      return global.crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      var v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  /* ── Deep freeze ── */
  function deepFreeze(obj) {
    if (!obj || typeof obj !== "object") { return obj; }
    try {
      Object.keys(obj).forEach(function (k) { deepFreeze(obj[k]); });
      Object.freeze(obj);
    } catch (e) { /* non-configurable descriptors */ }
    return obj;
  }

  /* ── ToolResult ── */
  function ToolResult(opts) {
    this.execId       = opts.execId;
    this.toolName     = opts.toolName;
    this.success      = opts.success;
    this.output       = opts.output !== undefined ? opts.output : null;
    this.error        = opts.error  || null;
    this.chunks       = opts.chunks || [];
    this.renderStats  = opts.renderStats || {};
    this.startedAt    = opts.startedAt;
    this.completedAt  = opts.completedAt || Date.now();
    this.retryCount   = opts.retryCount  || 0;
    deepFreeze(this);
  }

  /* ── SandboxedContext factory ── */
  function makeSandbox(execId, toolName, retryCount, streamCtx, abortCtrl, hookSet, bus, granted) {
    var meta = deepFreeze({
      execId     : execId,
      toolName   : toolName,
      retryCount : retryCount,
      startedAt  : Date.now()
    });
    return {
      signal      : abortCtrl.signal,
      metadata    : meta,
      permissions : granted.slice(),
      emitChunk   : function (chunk) { streamCtx.push(chunk); },
      emitEvent   : function (name, data) { bus.emit(name, { execId: execId, toolName: toolName, data: data }); },
      hasPermission : function (p) { return granted.indexOf(p) !== -1; },
      isCancelled : function () { return abortCtrl.signal && abortCtrl.signal.aborted; },
      logger      : {
        log  : function (msg) { console.log("[Tool:" + toolName + "] " + msg); },
        warn : function (msg) { console.warn("[Tool:" + toolName + "] " + msg); },
        error: function (msg) { console.error("[Tool:" + toolName + "] " + msg); }
      }
    };
  }

  /* ── ToolRuntime ── */
  function ToolRuntime(opts) {
    opts = opts || {};
    this._registry          = new ToolRegistry();
    this._bus               = new EventBus();
    this._hooks             = new HookSet();
    this._metrics           = new Metrics();
    this._activeCount       = 0;
    this._maxConcurrent     = opts.maxConcurrentExecutions || 10;
    this._queueLimit        = opts.queueLimit || 100;
    this._queue             = [];
    this._activeExecs       = {};
    this._grantedPermissions = opts.permissions || [];
    this._maxChunks         = opts.maxChunks    || 10000;
    this._maxChunkBytes     = opts.maxChunkBytes || 50 * 1024 * 1024;
    this._shuttingDown      = false;
    this._timers            = [];
  }

  /* ── Registration pass-through ── */
  ToolRuntime.prototype.register = function (name, def) {
    this._registry.register(name, def);
  };
  ToolRuntime.prototype.unregister = function (name) {
    this._registry.unregister(name);
  };
  ToolRuntime.prototype.has = function (name) {
    return this._registry.has(name);
  };
  ToolRuntime.prototype.list = function () {
    return this._registry.list();
  };

  /* ── Event / hook API ── */
  ToolRuntime.prototype.on = function (event, fn) {
    return this._bus.on(event, fn);
  };
  ToolRuntime.prototype.addHook = function (name, fn) {
    this._hooks.add(name, fn);
  };

  /* ── Grant / revoke permissions ── */
  ToolRuntime.prototype.grant = function (perms) {
    var self = this;
    (perms || []).forEach(function (p) {
      if (self._grantedPermissions.indexOf(p) === -1) {
        self._grantedPermissions.push(p);
      }
    });
  };
  ToolRuntime.prototype.revoke = function (perm) {
    var i = this._grantedPermissions.indexOf(perm);
    if (i !== -1) { this._grantedPermissions.splice(i, 1); }
  };

  /* ── Cancel ── */
  ToolRuntime.prototype.cancel = function (execId) {
    var entry = this._activeExecs[execId];
    if (!entry) { return false; }
    if (entry.abortCtrl && typeof entry.abortCtrl.abort === "function") {
      entry.abortCtrl.abort();
    }
    if (typeof entry.tryResolve === "function") {
      entry.tryResolve("cancel");
    }
    return true;
  };

  /* ── Execute ── */
  ToolRuntime.prototype.execute = function (name, args, opts) {
    var self = this;
    opts = opts || {};

    return new Promise(function (resolve, reject) {
      if (self._shuttingDown) {
        return reject(new ToolExecutionError("Runtime is shutting down"));
      }

      var def = self._registry.get(name);
      if (!def) {
        return reject(new ToolValidationError("Tool not found: " + name));
      }

      /* Permission check */
      var granted = opts.permissions || self._grantedPermissions;
      var permResult = Perm.check ? Perm.check(def.permissions, granted) : { allowed: true, missing: [] };
      if (!permResult.allowed) {
        return reject(new ToolPermissionError(
          "Missing permissions for '" + name + "': " + permResult.missing.join(", ")
        ));
      }

      /* Schema validation */
      try { validateSchema(args || {}, def.schema); }
      catch (e) { return reject(e); }

      /* Backpressure */
      if (self._activeCount >= self._maxConcurrent) {
        if (self._queue.length >= self._queueLimit) {
          return reject(new ToolExecutionError("Queue limit reached"));
        }
        self._queue.push({ name: name, args: args, opts: opts, resolve: resolve, reject: reject });
        return;
      }

      self._activeCount++;
      self._doExecute(name, args, opts, granted, def, resolve, reject);
    });
  };

  ToolRuntime.prototype._dequeue = function () {
    if (this._queue.length > 0 && this._activeCount < this._maxConcurrent) {
      var item = this._queue.shift();
      this._activeCount++;
      var def = this._registry.get(item.name);
      if (!def) {
        this._activeCount--;
        item.reject(new ToolValidationError("Tool not found after dequeue: " + item.name));
        this._dequeue();
        return;
      }
      var granted = item.opts.permissions || this._grantedPermissions;
      this._doExecute(item.name, item.args, item.opts, granted, def, item.resolve, item.reject);
    }
  };

  ToolRuntime.prototype._doExecute = function (name, args, opts, granted, def, resolve, reject) {
    var self    = this;
    var execId  = genUUID();
    var maxRetries = (opts.maxRetries !== undefined) ? opts.maxRetries : (def.maxRetries || 0);
    var startedAt  = Date.now();

    self._metrics.recordStart(name, execId);
    self._bus.emit("onStart", { execId: execId, toolName: name, args: args });
    self._hooks.fire("onStart", { execId: execId, toolName: name });

    var abortCtrl = global.AbortController ? new global.AbortController() : { signal: {}, abort: function () { this.signal.aborted = true; } };
    var resolved  = false;

    function tryResolve(outcome, valueOrErr) {
      if (resolved) { return; }
      resolved = true;
      delete self._activeExecs[execId];
      self._activeCount--;
      self._dequeue();

      if (outcome === "cancel") {
        var cancelErr = new ToolCancelledError("Execution cancelled: " + execId);
        self._metrics.recordEnd(name, execId, "cancel");
        self._bus.emit("onCancel", { execId: execId, toolName: name });
        self._hooks.fire("onCancel", { execId: execId, toolName: name });
        self._hooks.fire("onCleanup", { execId: execId, toolName: name });
        reject(cancelErr);
      } else if (outcome === "success") {
        self._metrics.recordEnd(name, execId, "success");
        self._bus.emit("onComplete", { execId: execId, toolName: name, result: valueOrErr });
        self._hooks.fire("onComplete", { execId: execId, toolName: name, result: valueOrErr });
        self._hooks.fire("onCleanup", { execId: execId, toolName: name });
        resolve(valueOrErr);
      } else {
        var finalOutcome = (valueOrErr && valueOrErr.name === "ToolTimeoutError") ? "timeout" : "error";
        self._metrics.recordEnd(name, execId, finalOutcome);
        self._bus.emit("onError", { execId: execId, toolName: name, error: valueOrErr });
        self._hooks.fire("onError", { execId: execId, toolName: name, error: valueOrErr });
        self._hooks.fire("onCleanup", { execId: execId, toolName: name });
        reject(valueOrErr);
      }
    }

    var execEntry = { execId: execId, toolName: name, abortCtrl: abortCtrl, tryResolve: tryResolve };
    self._activeExecs[execId] = execEntry;

    self._runWithRetry(name, args, opts, granted, def, execId, abortCtrl, startedAt, maxRetries, 0, tryResolve);
  };

  ToolRuntime.prototype._runWithRetry = function (name, args, opts, granted, def, execId, abortCtrl, startedAt, maxRetries, attempt, tryResolve) {
    var self    = this;
    var timeout = opts.timeout || def.timeout || 30000;

    var streamCtx = new StreamingContext({
      maxChunks    : opts.maxChunks    || self._maxChunks,
      maxChunkBytes: opts.maxChunkBytes || self._maxChunkBytes,
      onChunk      : function (chunk) {
        self._bus.emit("onChunk", { execId: execId, toolName: name, chunk: chunk });
      }
    });

    var sandbox = makeSandbox(execId, name, attempt, streamCtx, abortCtrl, self._hooks, self._bus, granted);

    var timerId = setTimeout(function () {
      /* Slice timerId from live list */
      var ti = self._timers.indexOf(timerId);
      if (ti !== -1) { self._timers.splice(ti, 1); }

      if (maxRetries > attempt && def.retryable !== false) {
        self._metrics.recordRetry(name);
        self._bus.emit("onRetry", { execId: execId, toolName: name, attempt: attempt + 1 });
        self._hooks.fire("onRetry", { execId: execId, toolName: name, attempt: attempt + 1 });
        self._runWithRetry(name, args, opts, granted, def, execId, abortCtrl, startedAt, maxRetries, attempt + 1, tryResolve);
      } else {
        tryResolve("error", new ToolTimeoutError("Tool '" + name + "' timed out after " + timeout + "ms"));
      }
    }, timeout);
    self._timers.push(timerId);

    var handlerPromise;
    try {
      handlerPromise = def.handler(args || {}, sandbox);
    } catch (syncErr) {
      clearTimeout(timerId);
      var ti2 = self._timers.indexOf(timerId);
      if (ti2 !== -1) { self._timers.splice(ti2, 1); }
      if (maxRetries > attempt && isRetryable(syncErr) && def.retryable !== false) {
        self._metrics.recordRetry(name);
        self._bus.emit("onRetry", { execId: execId, toolName: name, attempt: attempt + 1 });
        self._runWithRetry(name, args, opts, granted, def, execId, abortCtrl, startedAt, maxRetries, attempt + 1, tryResolve);
      } else {
        tryResolve("error", syncErr instanceof Error ? syncErr : new ToolExecutionError(String(syncErr)));
      }
      return;
    }

    if (!handlerPromise || typeof handlerPromise.then !== "function") {
      clearTimeout(timerId);
      var ti3 = self._timers.indexOf(timerId);
      if (ti3 !== -1) { self._timers.splice(ti3, 1); }
      var result = new ToolResult({
        execId: execId, toolName: name, success: true,
        output: handlerPromise, chunks: streamCtx.getChunks(),
        startedAt: startedAt, retryCount: attempt
      });
      tryResolve("success", result);
      return;
    }

    handlerPromise.then(
      function (output) {
        clearTimeout(timerId);
        var ti4 = self._timers.indexOf(timerId);
        if (ti4 !== -1) { self._timers.splice(ti4, 1); }
        var result = new ToolResult({
          execId: execId, toolName: name, success: true,
          output: output, chunks: streamCtx.getChunks(),
          startedAt: startedAt, retryCount: attempt
        });
        tryResolve("success", result);
      },
      function (err) {
        clearTimeout(timerId);
        var ti5 = self._timers.indexOf(timerId);
        if (ti5 !== -1) { self._timers.splice(ti5, 1); }
        if (!err || !(err instanceof Error)) {
          err = new ToolExecutionError(String(err));
        }
        if (maxRetries > attempt && isRetryable(err) && def.retryable !== false) {
          self._metrics.recordRetry(name);
          self._bus.emit("onRetry", { execId: execId, toolName: name, attempt: attempt + 1 });
          self._runWithRetry(name, args, opts, granted, def, execId, abortCtrl, startedAt, maxRetries, attempt + 1, tryResolve);
        } else {
          tryResolve("error", err);
        }
      }
    );
  };

  /* ── Metrics pass-through ── */
  ToolRuntime.prototype.getMetrics = function (name) {
    return this._metrics.get(name);
  };

  /* ── Shutdown ── */
  ToolRuntime.prototype.shutdown = function () {
    var self = this;
    self._shuttingDown = true;

    /* Cancel all active executions */
    Object.keys(self._activeExecs).forEach(function (execId) {
      self.cancel(execId);
    });

    /* Drain queue */
    while (self._queue.length) {
      var item = self._queue.shift();
      item.reject(new ToolExecutionError("Runtime shutdown"));
    }

    /* Clear all timers */
    self._timers.slice().forEach(function (id) { clearTimeout(id); });
    self._timers = [];

    /* Destroy event bus */
    if (typeof self._bus.destroy === "function") { self._bus.destroy(); }
    if (typeof self._hooks.clear === "function") { self._hooks.clear(); }
  };

  /* ── Session API ── */
  ToolRuntime.prototype.createSession = function (sessionOpts) {
    var self = this;
    var sessionPerms = (sessionOpts && sessionOpts.permissions) || self._grantedPermissions.slice();
    return {
      execute: function (name, args, opts) {
        opts = opts || {};
        opts.permissions = sessionPerms;
        return self.execute(name, args, opts);
      },
      cancel: function (execId) { return self.cancel(execId); },
      on    : function (event, fn) { return self._bus.on(event, fn); }
    };
  };

  ns.runtime = {
    ToolRuntime : ToolRuntime,
    ToolResult  : ToolResult,
    genUUID     : genUUID,
    deepFreeze  : deepFreeze
  };
})(window);
