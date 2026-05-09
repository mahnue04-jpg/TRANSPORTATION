const BASE_URL = process.env.AMICOR_BASE_URL || "http://127.0.0.1:8000";
const USER_ID = `cap_live_${Date.now()}`;

let passed = 0;
let failed = 0;

function ok(condition, message) {
  if (condition) {
    passed += 1;
    console.log(`  ✓ ${message}`);
  } else {
    failed += 1;
    console.error(`  ✗ ${message}`);
  }
}

async function requestJson(path, init) {
  const response = await fetch(`${BASE_URL}${path}`, init);
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (_) {
    data = text;
  }
  return { response, data };
}

async function testHealth() {
  console.log("\n► Health");
  const { response, data } = await requestJson("/api/health");
  ok(response.status === 200, "health endpoint returns 200");
  ok(data && data.status === "ok", "health payload reports ok");
}

async function testSearch() {
  console.log("\n► Real Web Search");
  const { response, data } = await requestJson("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID, message: "search for latest Microsoft earnings news" }),
  });
  ok(response.status === 200, "search request succeeds");
  ok(data.tool === "search" || data.tool === "news", "search routed to a live search capability");
  ok(data.status !== "error", "search capability does not return error status");
  ok(Array.isArray(data.sources) && data.sources.length > 0, "search returns attributed sources");
}

async function testWeather() {
  console.log("\n► Real Weather");
  const { response, data } = await requestJson("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID, message: "what's the weather in Seattle tomorrow?" }),
  });
  ok(response.status === 200, "weather request succeeds");
  ok(data.tool === "weather", "weather routed correctly");
  ok(data.status === "success" || data.status === "partial", "weather returns a live status");
  ok(String(data.reply || "").toLowerCase().includes("seattle"), "weather response is location-aware");
}

async function testTime() {
  console.log("\n► Real Time");
  const { response, data } = await requestJson("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID, message: "what time is it in Tokyo in 3 hours?" }),
  });
  ok(response.status === 200, "time request succeeds");
  ok(data.tool === "time", "time routed correctly");
  ok(String(data.reply || "").includes("Tokyo"), "time response references Tokyo");
  ok(String(data.reply || "").toLowerCase().includes("3 hours from now"), "time response includes scheduling hint");
}

async function testEmailDrafting() {
  console.log("\n► Email Drafting");
  const draft = await requestJson("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID, message: "draft a friendly email to Jordan about rescheduling tomorrow's meeting" }),
  });
  ok(draft.response.status === 200, "email draft request succeeds");
  ok(draft.data.tool === "email", "email routed correctly");
  ok(String(draft.data.reply || "").includes("Subject:"), "email draft includes subject");

  const send = await requestJson("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID, message: "send this email" }),
  });
  ok(send.response.status === 200, "email send simulation succeeds");
  ok(send.data.meta && send.data.meta.action === "send-simulated", "email send stays in simulation mode");
}

async function testUpload() {
  console.log("\n► Upload Parsing");
  const form = new FormData();
  const marker = "Capability live upload test payload.";
  form.append("file", new Blob([marker], { type: "text/plain" }), "capabilities-live.txt");
  const response = await fetch(`${BASE_URL}/api/upload`, { method: "POST", body: form });
  const data = await response.json();
  ok(response.status === 200, "upload request succeeds");
  ok(data.chunk_count >= 1, "upload returns chunk count");
  ok(data.diagnostics && data.diagnostics.parser === "utf8-text", "upload diagnostics identify parser");
  ok(String(data.extracted_text || "").includes(marker), "upload extracted text matches input");
}

async function testHistoryPersistence() {
  console.log("\n► Memory Persistence");
  const { response, data } = await requestJson(`/api/history/${USER_ID}?limit=20`);
  ok(response.status === 200, "history request succeeds");
  ok(Array.isArray(data.messages) && data.messages.length >= 10, "history persisted multiple turns");
  ok(data.memory && typeof data.memory === "object", "history response includes memory payload");
  ok(data.messages.some((message) => message.role === "assistant"), "history contains assistant responses");
}

async function testRecoveryHealth() {
  console.log("\n► Service Continuity");
  const { response, data } = await requestJson("/api/health");
  ok(response.status === 200, "health still succeeds after live capability calls");
  ok(data && data.status === "ok", "service remains healthy after execution burst");
}

async function main() {
  try {
    await testHealth();
    await testSearch();
    await testWeather();
    await testTime();
    await testEmailDrafting();
    await testUpload();
    await testHistoryPersistence();
    await testRecoveryHealth();
  } catch (error) {
    failed += 1;
    console.error("\nFatal live capability test error:", error.message);
  }

  const total = passed + failed;
  console.log("\n" + "=".repeat(72));
  console.log(`Capabilities Live: ${passed}/${total} checks passed`);
  console.log(failed === 0 ? "Status: ✅ ALL PASSED" : `Status: ❌ ${failed} FAILED`);
  console.log("=".repeat(72));

  process.exit(failed === 0 ? 0 : 1);
}

main();
