"use strict";

/**
 * apiConnector.js — External API connector with retry, timeout, and circuit breaking.
 * Uses Node.js built-in https/http modules only.
 */

const https = require("https");
const http = require("http");
const { URL } = require("url");

const {
  CONNECTOR_METHODS,
  INTEGRATION_ERRORS,
  uid,
  createApiRequest,
  createApiResponse,
  createIntegrationError,
} = require("./integrationSchemas");

const CIRCUIT_STATES = {
  closed:    "closed",    // normal operation
  open:      "open",      // failing: fast-fail
  halfOpen:  "half_open", // testing recovery
};

function createApiConnector(options) {
  var config = Object.assign(
    {
      baseUrl:              "",
      defaultHeaders:       {},
      defaultTimeoutMs:     30000,
      defaultRetries:       2,
      retryDelayMs:         500,
      retryBackoffFactor:   2,
      circuitBreakerEnabled: true,
      circuitThreshold:     5,     // failures before open
      circuitResetMs:       30000, // time before half-open
    },
    options || {}
  );

  // Metrics
  var metrics = {
    totalRequests: 0,
    succeeded:     0,
    failed:        0,
    retried:       0,
    timedOut:      0,
    circuitOpened: 0,
  };

  // Circuit breaker state
  var circuit = {
    state:        CIRCUIT_STATES.closed,
    failureCount: 0,
    openedAt:     null,
  };

  function circuitAllow() {
    if (!config.circuitBreakerEnabled) return true;
    if (circuit.state === CIRCUIT_STATES.closed) return true;
    if (circuit.state === CIRCUIT_STATES.open) {
      if (Date.now() - circuit.openedAt >= config.circuitResetMs) {
        circuit.state = CIRCUIT_STATES.halfOpen;
        return true;
      }
      return false;
    }
    if (circuit.state === CIRCUIT_STATES.halfOpen) return true;
    return true;
  }

  function circuitSuccess() {
    circuit.failureCount = 0;
    circuit.state = CIRCUIT_STATES.closed;
  }

  function circuitFailure() {
    circuit.failureCount += 1;
    if (circuit.state === CIRCUIT_STATES.halfOpen || circuit.failureCount >= config.circuitThreshold) {
      if (circuit.state !== CIRCUIT_STATES.open) metrics.circuitOpened += 1;
      circuit.state = CIRCUIT_STATES.open;
      circuit.openedAt = Date.now();
    }
  }

  function delay(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  /**
   * Make a raw HTTP/HTTPS request using Node built-ins.
   * Returns { status, headers, body(string) } or throws on network error/timeout.
   */
  function rawRequest(reqConfig) {
    return new Promise(function (resolve, reject) {
      var parsedUrl;
      try {
        parsedUrl = new URL(reqConfig.url);
      } catch (e) {
        reject(new Error("Invalid URL: " + reqConfig.url));
        return;
      }

      var isHttps = parsedUrl.protocol === "https:";
      var transport = isHttps ? https : http;

      var bodyStr = null;
      var headers = Object.assign({}, reqConfig.headers || {});

      if (reqConfig.body !== null && reqConfig.body !== undefined) {
        bodyStr = typeof reqConfig.body === "string" ? reqConfig.body : JSON.stringify(reqConfig.body);
        if (!headers["Content-Type"] && !headers["content-type"]) {
          headers["Content-Type"] = "application/json";
        }
        headers["Content-Length"] = Buffer.byteLength(bodyStr);
      }

      var reqOpts = {
        hostname: parsedUrl.hostname,
        port:     parsedUrl.port || (isHttps ? 443 : 80),
        path:     parsedUrl.pathname + parsedUrl.search,
        method:   reqConfig.method || "GET",
        headers:  headers,
      };

      var timedOut = false;
      var req = transport.request(reqOpts, function (res) {
        var chunks = [];
        res.on("data", function (c) { chunks.push(c); });
        res.on("end", function () {
          if (timedOut) return;
          resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString("utf8") });
        });
      });

      req.on("error", function (err) {
        if (timedOut) return;
        reject(err);
      });

      var timeout = reqConfig.timeout || config.defaultTimeoutMs;
      var timer = setTimeout(function () {
        timedOut = true;
        req.destroy();
        reject(Object.assign(new Error("Request timeout after " + timeout + "ms"), { code: "TIMEOUT" }));
      }, timeout);

      req.on("close", function () { clearTimeout(timer); });

      if (bodyStr) req.write(bodyStr);
      req.end();
    });
  }

  /**
   * Execute a request with retry and circuit breaker logic.
   */
  async function request(reqOptions) {
    metrics.totalRequests += 1;

    if (!circuitAllow()) {
      metrics.failed += 1;
      return createApiResponse({
        ok:        false,
        error:     INTEGRATION_ERRORS.requestFailed,
        body:      null,
        requestId: uid("req"),
      });
    }

    var url = reqOptions.url || "";
    if (config.baseUrl && !url.startsWith("http")) {
      url = config.baseUrl.replace(/\/$/, "") + "/" + url.replace(/^\//, "");
    }

    var reqCfg = createApiRequest({
      method:  reqOptions.method || CONNECTOR_METHODS.get,
      url:     url,
      headers: Object.assign({}, config.defaultHeaders, reqOptions.headers || {}),
      body:    reqOptions.body !== undefined ? reqOptions.body : null,
      timeout: reqOptions.timeout || config.defaultTimeoutMs,
      retries: reqOptions.retries !== undefined ? reqOptions.retries : config.defaultRetries,
    });

    var attempt = 0;
    var maxAttempts = reqCfg.retries + 1;
    var lastErr = null;
    var retryDelay = config.retryDelayMs;

    while (attempt < maxAttempts) {
      var start = Date.now();
      try {
        var raw = await rawRequest(reqCfg);
        var elapsed = Date.now() - start;
        var ok = raw.status >= 200 && raw.status < 300;

        var body = null;
        try { body = JSON.parse(raw.body); } catch (_) { body = raw.body; }

        if (ok) {
          metrics.succeeded += 1;
          circuitSuccess();
        } else {
          metrics.failed += 1;
          circuitFailure();
        }

        return createApiResponse({
          ok:         ok,
          status:     raw.status,
          body:       body,
          headers:    raw.headers,
          error:      ok ? null : (INTEGRATION_ERRORS.requestFailed + ":" + raw.status),
          durationMs: elapsed,
          requestId:  reqCfg.id,
          retries:    attempt,
        });
      } catch (err) {
        lastErr = err;
        attempt += 1;
        if (err.code === "TIMEOUT") metrics.timedOut += 1;
        circuitFailure();

        if (attempt < maxAttempts) {
          metrics.retried += 1;
          await delay(retryDelay);
          retryDelay = Math.min(retryDelay * config.retryBackoffFactor, 10000);
        }
      }
    }

    metrics.failed += 1;
    return createApiResponse({
      ok:        false,
      error:     lastErr && lastErr.code === "TIMEOUT" ? INTEGRATION_ERRORS.timeout : INTEGRATION_ERRORS.networkError,
      body:      null,
      requestId: reqCfg.id,
      retries:   attempt - 1,
      durationMs: 0,
    });
  }

  async function get(url, options) {
    return request(Object.assign({ method: CONNECTOR_METHODS.get, url }, options || {}));
  }

  async function post(url, body, options) {
    return request(Object.assign({ method: CONNECTOR_METHODS.post, url, body }, options || {}));
  }

  async function put(url, body, options) {
    return request(Object.assign({ method: CONNECTOR_METHODS.put, url, body }, options || {}));
  }

  async function patch(url, body, options) {
    return request(Object.assign({ method: CONNECTOR_METHODS.patch, url, body }, options || {}));
  }

  async function del(url, options) {
    return request(Object.assign({ method: CONNECTOR_METHODS.delete, url }, options || {}));
  }

  function getMetrics() { return Object.assign({}, metrics, { circuit: Object.assign({}, circuit) }); }

  function resetCircuit() {
    circuit.state = CIRCUIT_STATES.closed;
    circuit.failureCount = 0;
    circuit.openedAt = null;
  }

  return { request, get, post, put, patch, del, getMetrics, resetCircuit, CIRCUIT_STATES };
}

module.exports = { createApiConnector, CIRCUIT_STATES };
