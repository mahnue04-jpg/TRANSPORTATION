/* ─── runtime/metrics.js ─────────────────────────────────────────────────
 * Per-tool performance metrics with latency percentiles.
 * Exposed on window._AmiCorRT.metrics
 * ─────────────────────────────────────────────────────────────────────── */
(function (global) {
  "use strict";
  var ns = global._AmiCorRT = global._AmiCorRT || {};

  var MAX_SAMPLES = 1000;

  function sortedInsert(arr, val) {
    var lo = 0, hi = arr.length;
    while (lo < hi) {
      var mid = (lo + hi) >>> 1;
      if (arr[mid] < val) { lo = mid + 1; } else { hi = mid; }
    }
    arr.splice(lo, 0, val);
    if (arr.length > MAX_SAMPLES) { arr.shift(); }
  }

  function percentile(sorted, p) {
    if (!sorted.length) { return 0; }
    var idx = Math.ceil(p / 100 * sorted.length) - 1;
    return sorted[Math.max(0, idx)];
  }

  function ToolMetrics(name) {
    this.name         = name;
    this.callCount    = 0;
    this.successCount = 0;
    this.errorCount   = 0;
    this.cancelCount  = 0;
    this.timeoutCount = 0;
    this.retryCount   = 0;
    this.activeCount  = 0;
    this._starts      = {};        /* execId -> startMs */
    this._durations   = [];        /* sorted array of completed durations */
  }

  ToolMetrics.prototype.recordStart = function (execId) {
    this.callCount++;
    this.activeCount++;
    this._starts[execId] = Date.now();
  };

  ToolMetrics.prototype.recordEnd = function (execId, outcome) {
    var start = this._starts[execId];
    if (start !== undefined) {
      var dur = Date.now() - start;
      sortedInsert(this._durations, dur);
      delete this._starts[execId];
    }
    if (this.activeCount > 0) { this.activeCount--; }
    if (outcome === "success") { this.successCount++; }
    else if (outcome === "error") { this.errorCount++; }
    else if (outcome === "cancel") { this.cancelCount++; }
    else if (outcome === "timeout") { this.timeoutCount++; }
  };

  ToolMetrics.prototype.recordRetry = function () {
    this.retryCount++;
  };

  ToolMetrics.prototype.getSummary = function () {
    var d = this._durations;
    var n = d.length;
    var avg = n ? d.reduce(function (a, b) { return a + b; }, 0) / n : 0;
    var total = this.successCount + this.errorCount + this.cancelCount + this.timeoutCount;
    return {
      callCount    : this.callCount,
      successCount : this.successCount,
      errorCount   : this.errorCount,
      cancelCount  : this.cancelCount,
      timeoutCount : this.timeoutCount,
      retryCount   : this.retryCount,
      activeCount  : this.activeCount,
      avgDurationMs: Math.round(avg),
      failureRate  : total ? (this.errorCount + this.timeoutCount) / total : 0,
      latency      : {
        p50: percentile(d, 50),
        p95: percentile(d, 95),
        p99: percentile(d, 99)
      }
    };
  };

  function Metrics() {
    this._tools = {};
  }

  Metrics.prototype._get = function (name) {
    if (!this._tools[name]) { this._tools[name] = new ToolMetrics(name); }
    return this._tools[name];
  };

  Metrics.prototype.recordStart = function (name, execId) {
    this._get(name).recordStart(execId);
  };

  Metrics.prototype.recordEnd = function (name, execId, outcome) {
    this._get(name).recordEnd(execId, outcome);
  };

  Metrics.prototype.recordRetry = function (name) {
    this._get(name).recordRetry();
  };

  Metrics.prototype.get = function (name) {
    return this._get(name).getSummary();
  };

  Metrics.prototype.reset = function (name) {
    if (name) { delete this._tools[name]; }
    else       { this._tools = {}; }
  };

  ns.metrics = {
    Metrics     : Metrics,
    ToolMetrics : ToolMetrics,
    percentile  : percentile
  };
})(window);
