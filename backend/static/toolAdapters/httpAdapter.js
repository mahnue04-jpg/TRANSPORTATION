"use strict";

const http = require("http");
const https = require("https");

const { validateDomain, ensureWithinLimit, estimateSize } = require("../toolSecurity");
const { createToolError } = require("./baseAdapter");

function sleep(ms) {
  return new Promise(function (resolve) {
    setTimeout(resolve, ms);
  });
}

function raceTimeout(promise, timeoutMs, onTimeout) {
  if (!timeoutMs || timeoutMs <= 0) {
    return promise;
  }
  return new Promise(function (resolve, reject) {
    const timer = setTimeout(function () {
      try {
        if (typeof onTimeout === "function") {
          onTimeout();
        }
      } finally {
        reject(createToolError("request-timeout", "HTTP request timed out", { timeoutMs: timeoutMs }));
      }
    }, timeoutMs);

    promise.then(
      function (value) {
        clearTimeout(timer);
        resolve(value);
      },
      function (error) {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

function defaultTransport(parsedUrl, requestOptions, ctx) {
  return new Promise(function (resolve, reject) {
    const client = parsedUrl.protocol === "https:" ? https : http;
    const request = client.request(
      parsedUrl,
      {
        method: "GET",
        headers: requestOptions.headers || {},
      },
      function (response) {
        const chunks = [];
        let total = 0;
        response.on("data", function (chunk) {
          const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          total += buffer.length;
          if (requestOptions.maxResponseBytes && total > requestOptions.maxResponseBytes) {
            request.destroy(createToolError("response-too-large", "HTTP response exceeds size limit", {
              maxResponseBytes: requestOptions.maxResponseBytes,
            }));
            return;
          }
          chunks.push(buffer);
          if (ctx && typeof ctx.emitChunk === "function" && requestOptions.streamChunks) {
            ctx.emitChunk(buffer.toString("utf8"));
          }
        });
        response.on("end", function () {
          resolve({
            statusCode: response.statusCode || 0,
            headers: response.headers || {},
            body: Buffer.concat(chunks).toString("utf8"),
          });
        });
      }
    );

    request.on("error", reject);
    request.setTimeout(requestOptions.timeoutMs || 0, function () {
      request.destroy(createToolError("request-timeout", "HTTP request timed out", {
        timeoutMs: requestOptions.timeoutMs || 0,
      }));
    });
    if (ctx && ctx.signal && typeof ctx.signal.addEventListener === "function") {
      ctx.signal.addEventListener("abort", function () {
        request.destroy(createToolError("request-cancelled", "HTTP request cancelled"));
      });
    }
    request.end();
  });
}

function createHttpAdapter(options) {
  const config = Object.assign(
    {
      allowlist: [],
      timeoutMs: 5000,
      maxResponseBytes: 256 * 1024,
      retries: 1,
      retryDelayMs: 200,
      minIntervalMs: 0,
      headers: { "user-agent": "Amicor/real-tool-http" },
      transport: defaultTransport,
    },
    options || {}
  );

  const lastRequestAt = new Map();

  async function enforceRateLimit(hostname) {
    if (!config.minIntervalMs) {
      return;
    }
    const last = lastRequestAt.get(hostname) || 0;
    const elapsed = Date.now() - last;
    if (elapsed < config.minIntervalMs) {
      await sleep(config.minIntervalMs - elapsed);
    }
    lastRequestAt.set(hostname, Date.now());
  }

  async function get(args, ctx) {
    const parsedUrl = validateDomain(args.url, { allowlist: config.allowlist });
    if (args.method && String(args.method).toUpperCase() !== "GET") {
      throw createToolError("method-not-allowed", "HTTP tool only supports GET requests initially");
    }

    const attempts = Math.max(1, Number(args.retries) || config.retries + 1);
    let lastError = null;

    for (let attempt = 1; attempt <= attempts; attempt++) {
      try {
        await enforceRateLimit(parsedUrl.hostname);
        const response = await raceTimeout(
          Promise.resolve(
            config.transport(parsedUrl, {
              timeoutMs: config.timeoutMs,
              maxResponseBytes: config.maxResponseBytes,
              headers: Object.assign({}, config.headers, args.headers || {}),
              streamChunks: !!args.streamChunks,
            }, ctx)
          ),
          args.timeoutMs || config.timeoutMs,
          function () {
            if (ctx && ctx.signal && typeof ctx.signal.abort === "function") {
              ctx.signal.abort();
            }
          }
        );

        ensureWithinLimit(estimateSize(response.body || ""), config.maxResponseBytes, "HTTP response");
        return {
          url: parsedUrl.toString(),
          statusCode: response.statusCode || 200,
          headers: response.headers || {},
          body: response.body || "",
          bytes: estimateSize(response.body || ""),
          attempts: attempt,
        };
      } catch (error) {
        lastError = error;
        if (attempt < attempts) {
          await sleep(config.retryDelayMs * attempt);
          continue;
        }
        throw error;
      }
    }

    throw lastError || createToolError("request-failed", "HTTP request failed");
  }

  return {
    config: config,
    get: get,
  };
}

module.exports = { createHttpAdapter: createHttpAdapter };