// backend/static/ux/runtimeDiagnostics.js
// Live runtime diagnostics: Track API requests, responses, and performance

(function initRuntimeDiagnostics() {
  // ── Module Export ─────────────────────────────────────────────────────────
  const AmiCorDiagnostics = {
    isEnabled: true,
    requests: [],
    errors: [],
    performance: {},

    // Enable/disable logging
    enable() { this.isEnabled = true; },
    disable() { this.isEnabled = false; },

    // Get diagnostic summary
    getSummary() {
      return {
        totalRequests: this.requests.length,
        totalErrors: this.errors.length,
        avgLatency: this.getAverageLatency(),
        errorRate: this.getErrorRate(),
        recentErrors: this.errors.slice(-5),
        recentRequests: this.requests.slice(-10)
      };
    },

    // Get average latency
    getAverageLatency() {
      if (!this.requests.length) return 0;
      const sum = this.requests.reduce((acc, r) => acc + r.latency, 0);
      return Math.round(sum / this.requests.length);
    },

    // Get error rate (%)
    getErrorRate() {
      if (!this.requests.length) return 0;
      const errorCount = this.requests.filter(r => !r.ok).length;
      return Math.round((errorCount / this.requests.length) * 100);
    },

    // Log request
    logRequest(method, url, status, latency, ok) {
      const req = {
        timestamp: new Date().toISOString(),
        method,
        url,
        status,
        latency,
        ok
      };
      this.requests.push(req);
      if (!ok) {
        this.errors.push(req);
      }
      if (this.isEnabled) {
        console.log(`[DIAG] ${method} ${url} → ${status} (${latency}ms)`);
      }
    },

    // Log error
    logError(source, error, context) {
      const err = {
        timestamp: new Date().toISOString(),
        source,
        error: error.message || String(error),
        context,
        stack: error.stack
      };
      this.errors.push(err);
      if (this.isEnabled) {
        console.error(`[DIAG] ${source}: ${error.message}`, context);
      }
    },

    // Export diagnostics to JSON
    exportJSON() {
      return JSON.stringify({
        summary: this.getSummary(),
        allRequests: this.requests,
        allErrors: this.errors,
        exportedAt: new Date().toISOString()
      }, null, 2);
    },

    // Print summary to console
    printSummary() {
      const summary = this.getSummary();
      console.group('🔍 Amicor Runtime Diagnostics Summary');
      console.log(`Total Requests: ${summary.totalRequests}`);
      console.log(`Total Errors: ${summary.totalErrors}`);
      console.log(`Error Rate: ${summary.errorRate}%`);
      console.log(`Average Latency: ${summary.avgLatency}ms`);
      if (summary.recentErrors.length > 0) {
        console.group('Recent Errors:');
        summary.recentErrors.forEach(err => {
          console.error(`${err.timestamp}: ${err.method} ${err.url} → ${err.status}`);
        });
        console.groupEnd();
      }
      console.table(summary.recentRequests);
      console.groupEnd();
    }
  };

  // ── Intercept fetch requests ──────────────────────────────────────────────
  if (typeof window !== 'undefined') {
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
      const [resource, config] = args;
      const url = typeof resource === 'string' ? resource : resource.url;
      const method = (config?.method || 'GET').toUpperCase();
      const t0 = performance.now();

      return originalFetch.apply(this, args)
        .then(response => {
          const latency = Math.round(performance.now() - t0);
          AmiCorDiagnostics.logRequest(method, url, response.status, latency, response.ok);
          return response;
        })
        .catch(error => {
          const latency = Math.round(performance.now() - t0);
          AmiCorDiagnostics.logRequest(method, url, 0, latency, false);
          AmiCorDiagnostics.logError('fetch', error, { url, method });
          throw error;
        });
    };

    // Make diagnostics globally available
    window.AmiCorDiagnostics = AmiCorDiagnostics;

    // Log module load
    if (AmiCorDiagnostics.isEnabled) {
      console.log('✅ [DIAG] Diagnostics module loaded');
    }
  }

  // ── Node.js / CommonJS compatibility ──────────────────────────────────────
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AmiCorDiagnostics };
  }
})();
