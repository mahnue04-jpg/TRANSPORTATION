/**
 * Multimodal Tests — OCR pipeline, image upload, context injection
 * Run: npm run test:multimodal
 * Requires backend running on http://127.0.0.1:8000
 */

"use strict";

const http = require("http");
const fs   = require("fs");
const path = require("path");

const BASE_URL = "http://127.0.0.1:8000";
const PASS = "\x1b[32mPASS\x1b[0m";
const FAIL = "\x1b[31mFAIL\x1b[0m";
const SKIP = "\x1b[33mSKIP\x1b[0m";

let passed = 0, failed = 0, skipped = 0;

function assert(label, condition, detail = "") {
  if (condition) {
    console.log(`  ${PASS}  ${label}`);
    passed++;
  } else {
    console.log(`  ${FAIL}  ${label}${detail ? " — " + detail : ""}`);
    failed++;
  }
}

function skip(label, reason) {
  console.log(`  ${SKIP}  ${label} (${reason})`);
  skipped++;
}

function httpJson(method, path, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const raw = body ? JSON.stringify(body) : null;
    const opts = {
      hostname: "127.0.0.1",
      port: 8000,
      path,
      method,
      headers: {
        "Content-Type": "application/json",
        ...headers,
        ...(raw ? { "Content-Length": Buffer.byteLength(raw) } : {}),
      },
    };
    const req = http.request(opts, res => {
      let data = "";
      res.on("data", chunk => { data += chunk; });
      res.on("end", () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
        catch { resolve({ status: res.statusCode, body: data }); }
      });
    });
    req.on("error", reject);
    if (raw) req.write(raw);
    req.end();
  });
}

function httpMultipart(uploadPath, filename, mimeType, content) {
  return new Promise((resolve, reject) => {
    const boundary = "----MultimodalTestBoundary" + Date.now();
    const header = `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: ${mimeType}\r\n\r\n`;
    const footer = `\r\n--${boundary}--\r\n`;
    const body = Buffer.concat([
      Buffer.from(header),
      Buffer.isBuffer(content) ? content : Buffer.from(content),
      Buffer.from(footer),
    ]);
    const opts = {
      hostname: "127.0.0.1",
      port: 8000,
      path: uploadPath,
      method: "POST",
      headers: {
        "Content-Type": `multipart/form-data; boundary=${boundary}`,
        "Content-Length": body.length,
      },
    };
    const req = http.request(opts, res => {
      let data = "";
      res.on("data", c => { data += c; });
      res.on("end", () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
        catch { resolve({ status: res.statusCode, body: data }); }
      });
    });
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

// ── Minimal valid 1×1 PNG (67 bytes) ─────────────────────────────────────
const MINIMAL_PNG = Buffer.from(
  "89504e470d0a1a0a0000000d49484452000000010000000108020000009001" +
  "2e000000124944415408d7636060600000000200014ab9de1700000000049454e44ae426082",
  "hex"
);

// ── Tests ─────────────────────────────────────────────────────────────────

async function testImageUpload() {
  console.log("\n[1] Image Upload");
  try {
    const res = await httpMultipart("/api/upload", "test.png", "image/png", MINIMAL_PNG);
    assert("upload returns 200", res.status === 200, `got ${res.status}`);
    assert("response has ocr field", typeof res.body === "object" && "ocr" in res.body, JSON.stringify(res.body).slice(0, 100));
    if (res.body && res.body.ocr) {
      assert("ocr.method is a string", typeof res.body.ocr.method === "string");
      assert("ocr.confidence is a number", typeof res.body.ocr.confidence === "number");
      assert("ocr.word_count is a number", typeof res.body.ocr.word_count === "number");
    }
    assert("extracted_text present", typeof res.body === "object" && "extracted_text" in res.body);
    assert("status is uploaded", res.body.status === "uploaded");
  } catch (err) {
    assert("image upload (connection)", false, err.message);
  }
}

async function testImageUploadJpeg() {
  console.log("\n[2] JPEG Upload");
  // Minimal 1×1 JPEG
  const minJpeg = Buffer.from(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffffc0000b080001000101011100ffda00080101000000013f00ffffd9",
    "hex"
  );
  try {
    const res = await httpMultipart("/api/upload", "test.jpg", "image/jpeg", minJpeg);
    assert("jpeg upload 200", res.status === 200, `got ${res.status}`);
    assert("jpeg has ocr or extracted_text", res.body && ("ocr" in res.body || "extracted_text" in res.body));
  } catch (err) {
    assert("jpeg upload (connection)", false, err.message);
  }
}

async function testTextUpload() {
  console.log("\n[3] Text Upload (regression)");
  try {
    const content = "Hello from multimodal test suite";
    const res = await httpMultipart("/api/upload", "test.txt", "text/plain", content);
    assert("text upload 200", res.status === 200, `got ${res.status}`);
    assert("no ocr field for text", !(res.body && "ocr" in res.body));
    assert("extracted_text contains content", res.body && res.body.extracted_text && res.body.extracted_text.includes("Hello"));
  } catch (err) {
    assert("text upload (connection)", false, err.message);
  }
}

async function testProviderHealthEndpoint() {
  console.log("\n[4] Provider Diagnostics Endpoint");
  try {
    const res = await httpJson("GET", "/api/diagnostics/providers");
    assert("health endpoint returns 200", res.status === 200, `got ${res.status}`);
    assert("has providers field", res.body && typeof res.body.providers === "object");
  } catch (err) {
    assert("health endpoint (connection)", false, err.message);
  }
}

async function testStreamingEndpoint() {
  console.log("\n[5] Streaming Chat Endpoint");
  return new Promise(resolve => {
    const body = JSON.stringify({ user_id: "multimodal_test_user", message: "say hi briefly" });
    const opts = {
      hostname: "127.0.0.1",
      port: 8000,
      path: "/api/chat/stream",
      method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
    };
    const req = http.request(opts, res => {
      assert("stream returns 200", res.status === 200, `got ${res.status}`);
      const ct = res.headers["content-type"] || "";
      assert("content-type is event-stream", ct.includes("text/event-stream"), ct);

      let data = "";
      let gotToken = false;
      let gotDone = false;
      res.on("data", chunk => {
        data += chunk.toString();
        if (data.includes('"type":"token"') || data.includes('"type": "token"')) gotToken = true;
        if (data.includes('"type":"complete"') || data.includes('"type": "complete"')) gotToken = true;
        if (data.includes("[DONE]")) gotDone = true;
        if (gotDone) {
          assert("received at least one data event", gotToken);
          assert("received [DONE]", gotDone);
          res.destroy();
          resolve();
        }
      });
      res.on("end", () => {
        if (!gotDone) assert("received [DONE]", false, "stream ended without [DONE]");
        resolve();
      });
      setTimeout(() => { res.destroy(); resolve(); }, 15000);
    });
    req.on("error", err => { assert("streaming chat (connection)", false, err.message); resolve(); });
    req.write(body);
    req.end();
  });
}

async function testImageContextInChat() {
  console.log("\n[6] Image Context Injection in Chat");
  try {
    const body = {
      user_id: "multimodal_test_user",
      message: "[Image: invoice.png]\nVisual description: A simple test image\nExtracted text:\nFoo bar\n\nWhat is in this image?",
    };
    const res = await httpJson("POST", "/api/chat", body);
    assert("chat with image context returns 200", res.status === 200, `got ${res.status}`);
    assert("has reply field", res.body && typeof res.body.reply === "string");
  } catch (err) {
    assert("chat with image context (connection)", false, err.message);
  }
}

// ── Runner ────────────────────────────────────────────────────────────────

async function run() {
  console.log("═══════════════════════════════════════════════");
  console.log("  Amicore Multimodal Tests");
  console.log("═══════════════════════════════════════════════");

  await testImageUpload();
  await testImageUploadJpeg();
  await testTextUpload();
  await testProviderHealthEndpoint();
  await testStreamingEndpoint();
  await testImageContextInChat();

  console.log("\n───────────────────────────────────────────────");
  console.log(`  ${PASS} ${passed}  ${FAIL} ${failed}  ${SKIP} ${skipped}`);
  console.log("───────────────────────────────────────────────");
  if (failed > 0) process.exit(1);
}

run().catch(err => { console.error(err); process.exit(1); });
