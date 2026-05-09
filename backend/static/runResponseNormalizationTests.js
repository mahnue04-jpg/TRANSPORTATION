/**
 * Validation tests for API response normalization.
 * 
 * Verifies that all migrated endpoints use the standard response envelope:
 *   { ok: boolean, data: any, error: string|null, meta: {...} }
 */

async function testHealthEndpointNormalized() {
  const res = await fetch("http://localhost:8000/api/health");
  if (res.status !== 200) throw new Error(`Expected 200, got ${res.status}`);
  
  const body = await res.json();
  if (typeof body.ok !== "boolean") throw new Error("Response missing 'ok' boolean");
  if (body.ok !== true) throw new Error("Health check failed: ok=false");
  if (body.data === null) throw new Error("Response should have data for success");
  if (body.error !== null) throw new Error("Success response should have error=null");
  if (!body.meta) throw new Error("Response missing 'meta' object");
  
  console.log("✓ /api/health normalized response OK");
}

async function testHealthDetailEndpointNormalized() {
  const res = await fetch("http://localhost:8000/api/health/detail");
  const body = await res.json();
  
  // Should be normalized even if degraded
  if (typeof body.ok !== "boolean") throw new Error("Response missing 'ok' boolean");
  if (body.meta === undefined) throw new Error("Response missing 'meta' object");
  if (body.data === undefined) throw new Error("Response missing 'data'");
  
  // Health check includes diagnostic data
  if (body.data.status !== "healthy" && body.data.status !== "degraded") {
    throw new Error(`Invalid status: ${body.data.status}`);
  }
  
  console.log(`✓ /api/health/detail normalized response OK (status=${body.data.status})`);
}

async function testDiagnosticsProvidersNormalized() {
  const res = await fetch("http://localhost:8000/api/diagnostics/providers");
  if (res.status !== 200) throw new Error(`Expected 200, got ${res.status}`);
  
  const body = await res.json();
  if (typeof body.ok !== "boolean") throw new Error("Response missing 'ok' boolean");
  if (body.ok !== true) throw new Error("Diagnostics failed: ok=false");
  if (!Array.isArray(body.data.providers)) throw new Error("Providers should be array");
  if (body.error !== null) throw new Error("Success should have error=null");
  
  console.log("✓ /api/diagnostics/providers normalized response OK");
}

async function testChatEndpointNormalized() {
  const res = await fetch("http://localhost:8000/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: "test_user_response_validation",
      message: "What is 2+2?"
    })
  });
  
  if (res.status !== 200) throw new Error(`Expected 200, got ${res.status}`);
  
  const body = await res.json();
  if (typeof body.ok !== "boolean") throw new Error("Response missing 'ok' boolean");
  if (body.ok !== true) throw new Error(`Chat failed: ${body.error}`);
  if (body.data === null) throw new Error("Chat response should have data");
  if (!body.data.reply) throw new Error("Chat data missing 'reply'");
  if (body.error !== null) throw new Error("Success response should have error=null");
  
  console.log(`✓ /api/chat normalized response OK (reply length=${body.data.reply.length})`);
}

async function testErrorResponseNormalized() {
  // Trigger an error by sending invalid request
  const res = await fetch("http://localhost:8000/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: "", message: "" })  // Invalid: empty user_id
  });
  
  // Even error responses should be normalized
  const body = await res.json();
  if (typeof body.ok !== "boolean") throw new Error("Error response missing 'ok' boolean");
  if (body.ok !== false) throw new Error("Error response should have ok=false");
  if (body.error === null) throw new Error("Error response should have error message");
  if (body.data !== null && body.data !== undefined) throw new Error("Error response should have null data");
  
  console.log("✓ Error responses normalized OK");
}

async function runResponseNormalizationTests() {
  console.log("\n════════════════════════════════════════");
  console.log("API Response Normalization Validation");
  console.log("════════════════════════════════════════\n");
  
  const tests = [
    ["Health endpoint", testHealthEndpointNormalized],
    ["Health detail endpoint", testHealthDetailEndpointNormalized],
    ["Diagnostics providers", testDiagnosticsProvidersNormalized],
    ["Chat endpoint", testChatEndpointNormalized],
    ["Error response", testErrorResponseNormalized],
  ];
  
  let passed = 0;
  let failed = 0;
  
  for (const [name, test] of tests) {
    try {
      await test();
      passed++;
    } catch (err) {
      console.error(`✗ ${name} FAILED: ${err.message}`);
      failed++;
    }
  }
  
  console.log("\n════════════════════════════════════════");
  console.log(`TOTAL: ${passed} PASS, ${failed} FAIL`);
  console.log("════════════════════════════════════════\n");
  
  return failed === 0 ? 0 : 1;
}

// Export for use in Node.js
if (typeof module !== "undefined" && module.exports) {
  module.exports = { runResponseNormalizationTests };
}
