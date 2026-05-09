/**
 * tools.js — AmiCorToolRuntime
 *
 * Safe tool execution infrastructure for Amicor.
 * Manages tool registration, schema validation, execution lifecycle,
 * cancellation, timeouts, retries, streaming chunks, permissions,
 * structured results, and metrics.
 *
 * RESPONSIBILITIES (this module only):
 *   - Tool registry (register / unregister / lookup)
 *   - JSON-schema parameter validation
 *   - Execution lifecycle state machine
 *   - Cancellation via AbortController
 *   - Timeout enforcement
 *   - Retry with exponential back-off
 *   - Streaming chunk support (onChunk events during execution)
 *   - Permission model (allowlist / capability gates)
 *   - Structured ToolResult (success | error | cancelled | timeout)
 *   - Metrics (call count, avg latency, failure rate, active executions)
 *   - Isolated execution context (no global side-effects from tools)
 *
 * NON-RESPONSIBILITIES:
 *   - No DOM access
 *   - No markdown / LaTeX parsing
 *   - No orchestrator state management
 *   - No actual tool implementations (infrastructure only)
 *
 * ── Architecture ────────────────────────────────────────────────────────────
 *
 *   AI Model
 *   → AmiCorOrchestrator   (orchestrator.js)
 *   → AmiCorToolRuntime    (this file)       ← you are here
 *   → AmiCorStreamingEngine (streaming.js)
 *   → AmiCorRenderer        (render.js)
 *   → DOM
 *
 * ── Usage ────────────────────────────────────────────────────────────────────
 *
 *   // Register a tool:
 *   AmiCorToolRuntime.register({
 *     name: "calculator",
 *     description: "Evaluate a math expression",
 *     permissions: ["compute"],
 *     schema: {
 *       expression: { type: "string", required: true },
 *     },
 *     execute: function(args, ctx) {
 *       return { result: eval(args.expression) };   // demo only
 *     },
 *   });
 *
 *   // Execute a tool:
 *   AmiCorToolRuntime.execute("calculator", { expression: "2+2" })
 *     .then(function(result) { console.log(result); });
 *
 *   // Execute with options:
 *   AmiCorToolRuntime.execute("myTool", args, {
 *     timeoutMs: 5000,
 *     retryMax:  2,
 *     permissions: ["compute"],
 *     onChunk: function(chunk) { console.log("streaming:", chunk); },
 *   });
 *
 *   // Grant permissions to a session:
 *   var session = AmiCorToolRuntime.createSession({ permissions: ["compute"] });
 *   session.execute("calculator", { expression: "3*3" });
 *
 *   // Test suite:
 *   toolRuntimeTests();
 *
 * ── Future extension hooks ───────────────────────────────────────────────────
 *
 * FUTURE: Agent integration
 *   AmiCorToolRuntime.executeForAgent(agentId, toolName, args)
 *
 * FUTURE: Tool versioning
 *   register({ name: "search", version: "2.0", ... })
 *
 * FUTURE: Sandboxed execution
 *   execute inside a Web Worker or iframe sandbox
 *
 * FUTURE: Tool chaining
 *   runtime.chain([{ tool, args }, { tool, args }])
 *
 * FUTURE: Memory-augmented tools
 *   context passed to execute() will include memory snapshot
 *
 * FUTURE: Audit log
 *   persist all tool calls + results for compliance
 */

(function (global) {
  "use strict";

  // ───────────────────────────────────────────────────────────────────────────
  // Constants
  // ───────────────────────────────────────────────────────────────────────────

  var EXEC_STATES = {
    PENDING:   "pending",
    RUNNING:   "running",
    STREAMING: "streaming",
    COMPLETED: "completed",
    CANCELLED: "cancelled",
    TIMEOUT:   "timeout",
    FAILED:    "failed",
    RETRYING:  "retrying",
  };

  var TOOL_EVENTS = [
    "onToolRegister",
    "onToolUnregister",
    "onExecStart",
    "onExecChunk",
    "onExecComplete",
    "onExecCancel",
    "onExecTimeout",
    "onExecError",
    "onExecRetry",
    "onPermissionDenied",
    // Future hooks
    "onAuditLog",
    "onSandboxViolation",
  ];

  var DEFAULT_TIMEOUT_MS       = 10000;   // 10 s per execution
  var DEFAULT_RETRY_MAX        = 0;       // no retry by default
  var DEFAULT_RETRY_BASE_MS    = 300;     // exponential back-off base
  var MAX_RETRY_DELAY_MS       = 8000;

  // ───────────────────────────────────────────────────────────────────────────
  // Utilities
  // ───────────────────────────────────────────────────────────────────────────

  function uid() {
    return "tool-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
  }

  function now() { return Date.now(); }

  function deepFreeze(obj) {
    if (!obj || typeof obj !== "object") return obj;
    try {
      Object.freeze(obj);
      Object.keys(obj).forEach(function (k) { deepFreeze(obj[k]); });
    } catch (_) {}
    return obj;
  }

  function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
  }

  function retryDelay(attempt, baseMs) {
    return clamp(baseMs * Math.pow(2, attempt - 1), baseMs, MAX_RETRY_DELAY_MS);
  }

  function safeString(v) {
    if (v === null || v === undefined) return "";
    return String(v);
  }

  // ───────────────────────────────────────────────────────────────────────────
  // EventBus (minimal, mirrors orchestrator's pattern)
  // ───────────────────────────────────────────────────────────────────────────

  function EventBus(validEvents) {
    this._handlers = {};
    this._destroyed = false;
    var self = this;
    validEvents.forEach(function (e) { self._handlers[e] = []; });
  }

  EventBus.prototype.on = function (event, fn) {
    if (this._destroyed) return this;
    if (!this._handlers[event]) this._handlers[event] = [];
    this._handlers[event].push(fn);
    return this;
  };

  EventBus.prototype.off = function (event, fn) {
    if (!this._handlers[event]) return this;
    this._handlers[event] = this._handlers[event].filter(function (h) {
      return h !== fn;
    });
    return this;
  };

  EventBus.prototype.emit = function (event, payload) {
    if (this._destroyed) return;
    var handlers = this._handlers[event] || [];
    for (var i = 0; i < handlers.length; i++) {
      try { handlers[i](payload); } catch (e) {
        console.warn("[AmiCorToolRuntime] EventBus handler threw (" + event + "):", e);
      }
    }
  };

  EventBus.prototype.destroy = function () {
    this._destroyed = true;
    this._handlers = {};
  };

  // ───────────────────────────────────────────────────────────────────────────
  // Schema Validator
  // ───────────────────────────────────────────────────────────────────────────

  /**
   * Validate args against a simple schema.
   *
   * Schema format:
   *   {
   *     paramName: {
   *       type:     "string" | "number" | "boolean" | "object" | "array" | "any",
   *       required: true | false,
   *       enum:     ["a","b","c"],        (optional)
   *       minLength: N,                   (string only)
   *       maxLength: N,                   (string only)
   *       min: N,                         (number only)
   *       max: N,                         (number only)
   *     }
   *   }
   *
   * Returns: { valid: true } | { valid: false, errors: [...] }
   */
  function validateSchema(args, schema) {
    if (!schema) return { valid: true, errors: [] };
    var errors = [];

    // Check required fields and types
    Object.keys(schema).forEach(function (param) {
      var rule = schema[param];
      var val  = args[param];
      var absent = val === null || val === undefined;

      if (rule.required && absent) {
        errors.push({ param: param, code: "required", message: "'" + param + "' is required" });
        return;
      }
      if (absent) return;   // optional and missing — skip further checks

      // Type check
      var expectedType = rule.type || "any";
      if (expectedType !== "any") {
        var actualType = Array.isArray(val) ? "array" : typeof val;
        if (actualType !== expectedType) {
          errors.push({
            param: param,
            code: "type",
            message: "'" + param + "' must be " + expectedType + ", got " + actualType,
          });
          return;
        }
      }

      // Enum check
      if (rule.enum && rule.enum.indexOf(val) === -1) {
        errors.push({
          param: param,
          code: "enum",
          message: "'" + param + "' must be one of: " + rule.enum.join(", "),
        });
      }

      // String constraints
      if (typeof val === "string") {
        if (rule.minLength !== undefined && val.length < rule.minLength) {
          errors.push({ param: param, code: "minLength",
            message: "'" + param + "' must be at least " + rule.minLength + " chars" });
        }
        if (rule.maxLength !== undefined && val.length > rule.maxLength) {
          errors.push({ param: param, code: "maxLength",
            message: "'" + param + "' must be at most " + rule.maxLength + " chars" });
        }
      }

      // Number constraints
      if (typeof val === "number") {
        if (rule.min !== undefined && val < rule.min) {
          errors.push({ param: param, code: "min",
            message: "'" + param + "' must be >= " + rule.min });
        }
        if (rule.max !== undefined && val > rule.max) {
          errors.push({ param: param, code: "max",
            message: "'" + param + "' must be <= " + rule.max });
        }
      }
    });

    // Check for unknown params if schema has strict mode flag
    if (schema.__strict) {
      Object.keys(args || {}).forEach(function (k) {
        if (k !== "__strict" && !schema[k]) {
          errors.push({ param: k, code: "unknown", message: "Unknown parameter '" + k + "'" });
        }
      });
    }

    return { valid: errors.length === 0, errors: errors };
  }

  // ───────────────────────────────────────────────────────────────────────────
  // ToolResult — structured result envelope
  // ───────────────────────────────────────────────────────────────────────────

  function ToolResult(opts) {
    this.execId      = opts.execId;
    this.toolName    = opts.toolName;
    this.status      = opts.status;      // completed | error | cancelled | timeout
    this.output      = opts.output;      // any value the tool returns
    this.error       = opts.error || null;
    this.startedAt   = opts.startedAt;
    this.completedAt = opts.completedAt || now();
    this.durationMs  = this.completedAt - this.startedAt;
    this.retryCount  = opts.retryCount || 0;
    this.chunks      = opts.chunks || [];
    deepFreeze(this);
  }

  // ───────────────────────────────────────────────────────────────────────────
  // ExecutionContext — isolated context passed to tool.execute()
  // ───────────────────────────────────────────────────────────────────────────

  /**
   * Passed as the second argument to every tool.execute() call.
   * Gives tools a safe interface without exposing runtime internals.
   */
  function ExecutionContext(opts) {
    var self = this;
    self.execId      = opts.execId;
    self.toolName    = opts.toolName;
    self.signal      = opts.signal || null;   // AbortSignal
    self.permissions = opts.permissions.slice();

    // onChunk: tool calls this to emit streaming output
    self.emitChunk = function (chunk) {
      if (opts.onChunk) opts.onChunk(chunk);
    };

    // hasPermission: tool can self-check capabilities
    self.hasPermission = function (cap) {
      return opts.permissions.indexOf(cap) !== -1;
    };

    // isCancelled: polled by long-running tools
    self.isCancelled = function () {
      return !!(opts.signal && opts.signal.aborted);
    };
  }

  // ───────────────────────────────────────────────────────────────────────────
  // ToolRegistry
  // ───────────────────────────────────────────────────────────────────────────

  function ToolRegistry() {
    this._tools = {};
  }

  ToolRegistry.prototype.register = function (def) {
    if (!def || !def.name) throw new Error("[ToolRegistry] Tool definition must have a name");
    if (typeof def.execute !== "function") {
      throw new Error("[ToolRegistry] Tool '" + def.name + "' must have an execute() function");
    }
    var entry = {
      name:        def.name,
      description: def.description || "",
      schema:      def.schema || null,
      permissions: def.permissions || [],   // required capabilities
      execute:     def.execute,
      metadata:    def.metadata || {},
      registeredAt: now(),
    };
    this._tools[def.name] = entry;
    return entry;
  };

  ToolRegistry.prototype.unregister = function (name) {
    var had = !!this._tools[name];
    delete this._tools[name];
    return had;
  };

  ToolRegistry.prototype.get = function (name) {
    return this._tools[name] || null;
  };

  ToolRegistry.prototype.list = function () {
    return Object.keys(this._tools).map(function (k) {
      return {
        name:        this._tools[k].name,
        description: this._tools[k].description,
        permissions: this._tools[k].permissions.slice(),
        schema:      this._tools[k].schema,
      };
    }, this);
  };

  ToolRegistry.prototype.has = function (name) {
    return !!this._tools[name];
  };

  // ───────────────────────────────────────────────────────────────────────────
  // Metrics
  // ───────────────────────────────────────────────────────────────────────────

  function Metrics() {
    this._data = {};
  }

  Metrics.prototype._ensure = function (name) {
    if (!this._data[name]) {
      this._data[name] = {
        callCount:       0,
        successCount:    0,
        errorCount:      0,
        cancelCount:     0,
        timeoutCount:    0,
        retryCount:      0,
        totalDurationMs: 0,
        activeCount:     0,
      };
    }
    return this._data[name];
  };

  Metrics.prototype.recordStart = function (name) {
    this._ensure(name).callCount++;
    this._ensure(name).activeCount++;
  };

  Metrics.prototype.recordEnd = function (name, status, durationMs, retries) {
    var d = this._ensure(name);
    d.activeCount  = Math.max(0, d.activeCount - 1);
    d.totalDurationMs += durationMs || 0;
    d.retryCount   += retries || 0;
    if (status === "completed")  d.successCount++;
    if (status === "error" || status === "failed") d.errorCount++;
    if (status === "cancelled")  d.cancelCount++;
    if (status === "timeout")    d.timeoutCount++;
  };

  Metrics.prototype.get = function (name) {
    var d = this._data[name];
    if (!d) return null;
    var attempts = d.successCount + d.errorCount + d.cancelCount + d.timeoutCount;
    return {
      toolName:       name,
      callCount:      d.callCount,
      successCount:   d.successCount,
      errorCount:     d.errorCount,
      cancelCount:    d.cancelCount,
      timeoutCount:   d.timeoutCount,
      retryCount:     d.retryCount,
      activeCount:    d.activeCount,
      avgDurationMs:  attempts > 0 ? Math.round(d.totalDurationMs / attempts) : 0,
      failureRate:    attempts > 0 ? (d.errorCount + d.timeoutCount) / attempts : 0,
    };
  };

  Metrics.prototype.getAll = function () {
    return Object.keys(this._data).map(this.get, this);
  };

  Metrics.prototype.reset = function (name) {
    if (name) delete this._data[name];
    else this._data = {};
  };

  // ───────────────────────────────────────────────────────────────────────────
  // ToolRuntime — core executor
  // ───────────────────────────────────────────────────────────────────────────

  function ToolRuntime(opts) {
    opts = opts || {};
    this._registry    = new ToolRegistry();
    this._bus         = new EventBus(TOOL_EVENTS);
    this._metrics     = new Metrics();
    this._executions  = {};   // execId → { state, controller, timer }
    this._defaultPermissions = opts.permissions || [];
    this._defaultTimeoutMs   = opts.timeoutMs !== undefined
      ? opts.timeoutMs : DEFAULT_TIMEOUT_MS;
    this._destroyed   = false;
  }

  // ── Event bus delegation ──────────────────────────────────────────────────

  ToolRuntime.prototype.on  = function (e, fn) { this._bus.on(e, fn);  return this; };
  ToolRuntime.prototype.off = function (e, fn) { this._bus.off(e, fn); return this; };

  // ── Registry delegation ───────────────────────────────────────────────────

  ToolRuntime.prototype.register = function (def) {
    this._assertAlive();
    var entry = this._registry.register(def);
    this._bus.emit("onToolRegister", { toolName: def.name, entry: entry });
    return this;
  };

  ToolRuntime.prototype.unregister = function (name) {
    var had = this._registry.unregister(name);
    if (had) this._bus.emit("onToolUnregister", { toolName: name });
    return had;
  };

  ToolRuntime.prototype.listTools   = function () { return this._registry.list(); };
  ToolRuntime.prototype.hasTool     = function (name) { return this._registry.has(name); };
  ToolRuntime.prototype.getMetrics  = function (name) {
    return name ? this._metrics.get(name) : this._metrics.getAll();
  };

  // ── Main execute() ────────────────────────────────────────────────────────

  /**
   * Execute a registered tool.
   *
   * @param {string} toolName
   * @param {object} args        - tool arguments (validated against schema)
   * @param {object} [opts]
   *   @param {string[]} opts.permissions  - caller's permission set
   *   @param {number}   opts.timeoutMs    - override timeout
   *   @param {number}   opts.retryMax     - override retry limit
   *   @param {function} opts.onChunk      - streaming chunk callback
   *   @param {string}   opts.execId       - override execution id
   * @returns {Promise<ToolResult>}
   */
  ToolRuntime.prototype.execute = function (toolName, args, opts) {
    this._assertAlive();
    var self    = this;
    opts        = opts || {};
    var execId  = opts.execId || uid();
    var callerPerms = opts.permissions !== undefined
      ? opts.permissions : this._defaultPermissions.slice();
    var timeoutMs = opts.timeoutMs !== undefined
      ? opts.timeoutMs : this._defaultTimeoutMs;
    var retryMax = opts.retryMax !== undefined
      ? opts.retryMax : DEFAULT_RETRY_MAX;

    return new Promise(function (resolve) {
      self._executeWithRetry({
        toolName:    toolName,
        args:        args || {},
        execId:      execId,
        permissions: callerPerms,
        timeoutMs:   timeoutMs,
        retryMax:    retryMax,
        onChunk:     opts.onChunk || null,
        retryCount:  0,
        startedAt:   now(),
        resolve:     resolve,
      });
    });
  };

  ToolRuntime.prototype._executeWithRetry = function (ctx) {
    var self = this;
    self._executeSingle(ctx, function (result) {
      // If failed (not cancelled/timeout) and retries remain → retry
      if (
        result.status === "error" &&
        ctx.retryCount < ctx.retryMax
      ) {
        ctx.retryCount++;
        self._metrics.recordEnd(ctx.toolName, "error", result.durationMs, 0);
        self._bus.emit("onExecRetry", {
          execId:     ctx.execId,
          toolName:   ctx.toolName,
          retryCount: ctx.retryCount,
          error:      result.error,
        });
        var delay = retryDelay(ctx.retryCount, DEFAULT_RETRY_BASE_MS);
        setTimeout(function () {
          self._executeWithRetry(ctx);
        }, delay);
        return;
      }
      // Record metrics (retries already counted per-attempt above for error path)
      self._metrics.recordEnd(ctx.toolName, result.status, result.durationMs, ctx.retryCount);
      ctx.resolve(result);
    });
  };

  ToolRuntime.prototype._executeSingle = function (ctx, done) {
    var self      = this;
    var tool      = this._registry.get(ctx.toolName);
    var startedAt = ctx.startedAt || now();

    // ── Tool not found ────────────────────────────────────────────────────
    if (!tool) {
      var notFound = new ToolResult({
        execId: ctx.execId, toolName: ctx.toolName,
        status: "error", output: null,
        error: new Error("Tool not found: " + ctx.toolName),
        startedAt: startedAt,
      });
      done(notFound); return;
    }

    // ── Permission check ──────────────────────────────────────────────────
    var missingPerms = tool.permissions.filter(function (p) {
      return ctx.permissions.indexOf(p) === -1;
    });
    if (missingPerms.length > 0) {
      self._bus.emit("onPermissionDenied", {
        execId: ctx.execId, toolName: ctx.toolName,
        required: missingPerms, granted: ctx.permissions,
      });
      var permResult = new ToolResult({
        execId: ctx.execId, toolName: ctx.toolName,
        status: "error", output: null,
        error: new Error("Permission denied. Missing: " + missingPerms.join(", ")),
        startedAt: startedAt,
      });
      done(permResult); return;
    }

    // ── Schema validation ─────────────────────────────────────────────────
    if (tool.schema) {
      var validation = validateSchema(ctx.args, tool.schema);
      if (!validation.valid) {
        var validResult = new ToolResult({
          execId: ctx.execId, toolName: ctx.toolName,
          status: "error", output: null,
          error: Object.assign(
            new Error("Schema validation failed: " +
              validation.errors.map(function (e) { return e.message; }).join("; ")
            ),
            { validationErrors: validation.errors }
          ),
          startedAt: startedAt,
        });
        done(validResult); return;
      }
    }

    // ── AbortController setup ─────────────────────────────────────────────
    var controller = null;
    var signal     = null;
    if (typeof AbortController !== "undefined") {
      controller = new AbortController();
      signal     = controller.signal;
    }

    // ── Execution tracking ────────────────────────────────────────────────
    var execEntry = {
      state:      EXEC_STATES.PENDING,
      controller: controller,
      timer:      null,
      toolName:   ctx.toolName,
      execId:     ctx.execId,
    };
    self._executions[ctx.execId] = execEntry;

    // ── Chunk collector ───────────────────────────────────────────────────
    var chunks   = [];
    var timedOut = false;
    var cancelled = false;

    function onChunk(chunk) {
      chunks.push(chunk);
      self._bus.emit("onExecChunk", {
        execId: ctx.execId, toolName: ctx.toolName, chunk: chunk,
      });
      if (ctx.onChunk) {
        try { ctx.onChunk(chunk); } catch (_) {}
      }
    }

    // ── Metrics: start ────────────────────────────────────────────────────
    self._metrics.recordStart(ctx.toolName);
    execEntry.state = EXEC_STATES.RUNNING;

    self._bus.emit("onExecStart", {
      execId: ctx.execId, toolName: ctx.toolName,
      args: ctx.args, retryCount: ctx.retryCount,
    });

    // ── Timeout ───────────────────────────────────────────────────────────
    if (ctx.timeoutMs > 0) {
      execEntry.timer = setTimeout(function () {
        timedOut = true;
        if (controller) controller.abort();
        execEntry.state = EXEC_STATES.TIMEOUT;
        self._bus.emit("onExecTimeout", {
          execId: ctx.execId, toolName: ctx.toolName, timeoutMs: ctx.timeoutMs,
        });
        cleanup();
        done(new ToolResult({
          execId: ctx.execId, toolName: ctx.toolName,
          status: "timeout", output: null,
          error: new Error("Tool '" + ctx.toolName + "' timed out after " + ctx.timeoutMs + "ms"),
          startedAt: startedAt, chunks: chunks, retryCount: ctx.retryCount,
        }));
      }, ctx.timeoutMs);
    }

    function cleanup() {
      if (execEntry.timer) { clearTimeout(execEntry.timer); execEntry.timer = null; }
      delete self._executions[ctx.execId];
    }

    // ── Execution context ─────────────────────────────────────────────────
    var execCtx = new ExecutionContext({
      execId:      ctx.execId,
      toolName:    ctx.toolName,
      signal:      signal,
      permissions: ctx.permissions,
      onChunk:     onChunk,
    });

    // ── Call the tool ─────────────────────────────────────────────────────
    var returnVal;
    try {
      returnVal = tool.execute(ctx.args, execCtx);
    } catch (syncErr) {
      if (timedOut) return;
      cleanup();
      execEntry.state = EXEC_STATES.FAILED;
      self._bus.emit("onExecError", {
        execId: ctx.execId, toolName: ctx.toolName, error: syncErr,
      });
      done(new ToolResult({
        execId: ctx.execId, toolName: ctx.toolName,
        status: "error", output: null, error: syncErr,
        startedAt: startedAt, chunks: chunks, retryCount: ctx.retryCount,
      }));
      return;
    }

    // ── Handle async / sync return ────────────────────────────────────────
    var resultPromise;
    if (returnVal && typeof returnVal.then === "function") {
      resultPromise = returnVal;
    } else {
      resultPromise = { then: function (fn) { fn(returnVal); return this; }, _sync: true };
    }

    resultPromise.then(
      function (output) {
        if (timedOut || cancelled) return;
        cleanup();
        execEntry.state = EXEC_STATES.COMPLETED;
        var res = new ToolResult({
          execId: ctx.execId, toolName: ctx.toolName,
          status: "completed", output: output,
          startedAt: startedAt, chunks: chunks, retryCount: ctx.retryCount,
        });
        self._bus.emit("onExecComplete", {
          execId: ctx.execId, toolName: ctx.toolName, result: res,
        });
        done(res);
      },
      function (err) {
        if (timedOut || cancelled) return;
        cleanup();
        execEntry.state = EXEC_STATES.FAILED;
        self._bus.emit("onExecError", {
          execId: ctx.execId, toolName: ctx.toolName, error: err,
        });
        done(new ToolResult({
          execId: ctx.execId, toolName: ctx.toolName,
          status: "error", output: null, error: err,
          startedAt: startedAt, chunks: chunks, retryCount: ctx.retryCount,
        }));
      }
    );
  };

  // ── cancel() ─────────────────────────────────────────────────────────────

  ToolRuntime.prototype.cancel = function (execId) {
    var entry = this._executions[execId];
    if (!entry) return false;
    if (entry.controller) entry.controller.abort();
    if (entry.timer) { clearTimeout(entry.timer); entry.timer = null; }
    entry.state = EXEC_STATES.CANCELLED;
    delete this._executions[execId];
    this._bus.emit("onExecCancel", { execId: execId, toolName: entry.toolName });
    return true;
  };

  ToolRuntime.prototype.cancelAll = function () {
    Object.keys(this._executions).forEach(this.cancel, this);
  };

  ToolRuntime.prototype.activeExecutions = function () {
    return Object.keys(this._executions).map(function (id) {
      var e = this._executions[id];
      return { execId: e.execId, toolName: e.toolName, state: e.state };
    }, this);
  };

  // ── Session ───────────────────────────────────────────────────────────────

  /**
   * Create a scoped session with pre-granted permissions.
   * All executions from the session inherit those permissions.
   */
  ToolRuntime.prototype.createSession = function (opts) {
    opts = opts || {};
    var runtime     = this;
    var permissions = opts.permissions || [];
    var destroyed   = false;
    var sessionBus  = new EventBus(TOOL_EVENTS);

    // Forward runtime global events to session bus
    var forwarders = {};
    TOOL_EVENTS.forEach(function (e) {
      forwarders[e] = function (p) { sessionBus.emit(e, p); };
      runtime.on(e, forwarders[e]);
    });

    var session = {
      permissions: permissions.slice(),

      on:  function (e, fn) { sessionBus.on(e, fn);  return session; },
      off: function (e, fn) { sessionBus.off(e, fn); return session; },

      execute: function (toolName, args, execOpts) {
        if (destroyed) return Promise.reject(new Error("Session destroyed"));
        var merged = Object.assign({}, execOpts || {});
        // Merge session permissions with per-call overrides
        merged.permissions = (execOpts && execOpts.permissions)
          ? session.permissions.concat(execOpts.permissions)
          : session.permissions.slice();
        return runtime.execute(toolName, args, merged);
      },

      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        TOOL_EVENTS.forEach(function (e) { runtime.off(e, forwarders[e]); });
        sessionBus.destroy();
      },
    };

    return session;
  };

  // ── destroy ───────────────────────────────────────────────────────────────

  ToolRuntime.prototype.destroy = function () {
    this.cancelAll();
    this._bus.destroy();
    this._destroyed = true;
  };

  ToolRuntime.prototype._assertAlive = function () {
    if (this._destroyed) throw new Error("[AmiCorToolRuntime] Runtime has been destroyed");
  };

  // ───────────────────────────────────────────────────────────────────────────
  // Global singleton + factory
  // ───────────────────────────────────────────────────────────────────────────

  var _defaultRuntime = new ToolRuntime();

  var AmiCorToolRuntime = {
    // Singleton API (delegates to default runtime)
    register:         function (def)              { return _defaultRuntime.register(def); },
    unregister:       function (name)             { return _defaultRuntime.unregister(name); },
    execute:          function (n, a, o)          { return _defaultRuntime.execute(n, a, o); },
    cancel:           function (execId)           { return _defaultRuntime.cancel(execId); },
    cancelAll:        function ()                 { return _defaultRuntime.cancelAll(); },
    on:               function (e, fn)            { _defaultRuntime.on(e, fn); return AmiCorToolRuntime; },
    off:              function (e, fn)            { _defaultRuntime.off(e, fn); return AmiCorToolRuntime; },
    listTools:        function ()                 { return _defaultRuntime.listTools(); },
    hasTool:          function (name)             { return _defaultRuntime.hasTool(name); },
    getMetrics:       function (name)             { return _defaultRuntime.getMetrics(name); },
    activeExecutions: function ()                 { return _defaultRuntime.activeExecutions(); },
    createSession:    function (opts)             { return _defaultRuntime.createSession(opts); },

    // Factory: create an isolated runtime instance
    createRuntime:    function (opts)             { return new ToolRuntime(opts); },

    // Exposed internals for testing
    _validateSchema:  validateSchema,
    _ToolResult:      ToolResult,
    _ExecutionContext: ExecutionContext,
    _EXEC_STATES:     EXEC_STATES,
    _ToolRuntime:     ToolRuntime,
  };

  global.AmiCorToolRuntime = AmiCorToolRuntime;

})(window);
