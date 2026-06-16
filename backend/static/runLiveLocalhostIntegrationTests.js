#!/usr/bin/env node
"use strict";

const http = require("http");

const BASE_URL = "http://127.0.0.1:8011";
const APP_PATH = "/app";

let passed = 0;
let failed = 0;

function ok(condition, label, detail) {
  if (condition) {
    passed += 1;
    console.log("  ✓", label);
    return;
  }
  failed += 1;
  console.error("  ✗", label + (detail ? " — " + detail : ""));
}

function request(method, path, body) {
  return new Promise((resolve, reject) => {
    const payload = body ? Buffer.from(JSON.stringify(body), "utf8") : null;
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port: 8011,
        method,
        path,
        headers: payload
          ? {
              "Content-Type": "application/json",
              "Content-Length": String(payload.length),
            }
          : {},
        timeout: 15000,
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          resolve({ status: res.statusCode || 0, text, headers: res.headers || {} });
        });
      }
    );

    req.on("timeout", () => {
      req.destroy(new Error("Request timed out"));
    });
    req.on("error", reject);

    if (payload) req.write(payload);
    req.end();
  });
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch (_) {
    return null;
  }
}

async function run() {
  console.log("\nLocalhost Integrated Runtime Verification");
  console.log("Target:", BASE_URL + APP_PATH);

  const app = await request("GET", APP_PATH);
  ok(app.status === 200, "GET /app succeeds", "status=" + app.status);
  ok(/AmiCorVoiceDebug/.test(app.text), "Runtime debug API is present in served app");
  ok(/runUnifiedLocalhostIntegrationVerification/.test(app.text), "Unified localhost verification helper is present");
  ok(/EXPECTED_LOCAL_RUNTIME_ORIGIN\s*=\s*"http:\/\/127\.0\.0\.1:8011"/.test(app.text), "Localhost origin enforcement is configured");
  ok(/\[RUNTIME_ENV_LOCALHOST\]/.test(app.text), "Localhost runtime environment diagnostic tag is present");
  ok(/\[RUNTIME_ENV_FILE_MODE\]/.test(app.text), "File mode runtime diagnostic tag is present");
  ok(/\[SECURE_CONTEXT_CONFIRMED\]/.test(app.text), "Secure context diagnostic tag is present");
  ok(/\[VOICE_RUNTIME_READY\]/.test(app.text), "Voice runtime readiness diagnostic tag is present");
  ok(/\[MEMORY_RUNTIME_READY\]/.test(app.text), "Memory runtime readiness diagnostic tag is present");
  ok(/\[DIAGNOSTICS_RUNTIME_READY\]/.test(app.text), "Diagnostics runtime readiness diagnostic tag is present");

  const testUser = "localhost_verify_" + Date.now();

  const reset = await request("POST", "/api/reset", { user_id: testUser });
  const resetJson = parseJson(reset.text);
  ok(reset.status === 200, "POST /api/reset succeeds", "status=" + reset.status);
  ok(!!(resetJson && resetJson.success === true), "Memory reset returns success=true");

  const seed = await request("POST", "/api/chat", {
    user_id: testUser,
    message: "my name is Saye and I prefer concise replies",
  });
  const seedJson = parseJson(seed.text);
  ok(seed.status === 200, "POST /api/chat seed message succeeds", "status=" + seed.status);
  ok(!!(seedJson && seedJson.ok === true), "Seed message returns normalized success envelope");

  const askName = await request("POST", "/api/chat", {
    user_id: testUser,
    message: "What is my name?",
  });
  const askNameJson = parseJson(askName.text);
  const askNameReply = String(askNameJson && askNameJson.data && askNameJson.data.reply || "");
  ok(askName.status === 200, "POST /api/chat name recall succeeds", "status=" + askName.status);
  ok(/your\s+name\s+is\s+saye/i.test(askNameReply), "Name recall returns expected memory response");

  const historyBeforeReset = await request("GET", "/api/history/" + encodeURIComponent(testUser) + "?limit=20");
  const historyBeforeResetJson = parseJson(historyBeforeReset.text);
  const memorySummaryBeforeReset = String(
    historyBeforeResetJson &&
    historyBeforeResetJson.memory &&
    historyBeforeResetJson.memory.summary ||
    ""
  );
  ok(historyBeforeReset.status === 200, "GET /api/history before reset succeeds", "status=" + historyBeforeReset.status);
  ok(/saye/i.test(memorySummaryBeforeReset), "History memory summary contains remembered name before reset");

  const clear = await request("POST", "/api/reset", { user_id: testUser });
  const clearJson = parseJson(clear.text);
  ok(clear.status === 200, "POST /api/reset after memory seed succeeds", "status=" + clear.status);
  ok(!!(clearJson && clearJson.success === true), "Reset after seed returns success=true");

  const askNameAfterReset = await request("POST", "/api/chat", {
    user_id: testUser,
    message: "What is my name?",
  });
  const askNameAfterResetJson = parseJson(askNameAfterReset.text);
  const askNameAfterResetReply = String(askNameAfterResetJson && askNameAfterResetJson.data && askNameAfterResetJson.data.reply || "");
  ok(askNameAfterReset.status === 200, "POST /api/chat name recall after reset succeeds", "status=" + askNameAfterReset.status);
  ok(!/your\s+name\s+is\s+saye/i.test(askNameAfterResetReply), "After reset, assistant no longer claims remembered name");

  const historyAfterReset = await request("GET", "/api/history/" + encodeURIComponent(testUser) + "?limit=20");
  const historyAfterResetJson = parseJson(historyAfterReset.text);
  const memorySummaryAfterReset = String(
    historyAfterResetJson &&
    historyAfterResetJson.memory &&
    historyAfterResetJson.memory.summary ||
    ""
  );
  ok(historyAfterReset.status === 200, "GET /api/history after reset succeeds", "status=" + historyAfterReset.status);
  ok(!/saye/i.test(memorySummaryAfterReset), "History memory summary cleared after reset");

  const selfRef = await request("POST", "/api/chat", {
    user_id: testUser,
    message: "what do you know about Saye",
  });
  const selfRefJson = parseJson(selfRef.text);
  const reply = String(selfRefJson && selfRefJson.data && selfRefJson.data.reply || "");
  ok(selfRef.status === 200, "POST /api/chat self-reference succeeds", "status=" + selfRef.status);
  ok(/your\s+name\s+is\s+saye/i.test(reply), "Self-reference routing resolves canonical user entity");
  ok(!/refer\s+to\s+various\s+subjects/i.test(reply), "Generic encyclopedia fallback is blocked for canonical user entity");

  const stream = await request("POST", "/api/chat/stream", {
    user_id: testUser,
    message: "say hello in one sentence",
  });
  ok(stream.status === 200, "POST /api/chat/stream succeeds", "status=" + stream.status);
  ok(/data:\s*\{\"type\":\s*\"token\"/i.test(stream.text) || /data:\s*\{\"type\":\s*\"complete\"/i.test(stream.text), "Streaming returns SSE token/complete events");
  ok(/data:\s*\[DONE\]/i.test(stream.text), "Streaming returns terminal [DONE] event");

  const history = await request("GET", "/api/history/" + encodeURIComponent(testUser) + "?limit=20");
  const historyJson = parseJson(history.text);
  const historyMessages = Array.isArray(historyJson && historyJson.messages) ? historyJson.messages : [];
  ok(history.status === 200, "GET /api/history succeeds", "status=" + history.status);
  ok(historyMessages.length >= 3, "Replay restoration continuity is available in persisted history");

  console.log("\nSummary");
  console.log("Passed:", passed);
  console.log("Failed:", failed);
  process.exit(failed > 0 ? 1 : 0);
}

run().catch((error) => {
  console.error("\nLocalhost integrated runtime verification failed to execute:", error && error.message ? error.message : error);
  process.exit(1);
});
