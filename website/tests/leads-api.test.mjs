import assert from "node:assert/strict";
import { handleLead } from "../functions/api/leads.js";

class MemoryKv {
  constructor() {
    this.items = new Map();
    this.failPut = false;
  }

  async get(key) {
    const row = this.items.get(key);
    if (!row) return null;
    if (row.expiresAt && Date.now() > row.expiresAt) {
      this.items.delete(key);
      return null;
    }
    return row.value;
  }

  async put(key, value, options = {}) {
    if (this.failPut) throw new Error("kv down");
    const ttl = Number(options.expirationTtl || 0);
    this.items.set(key, {
      value,
      expiresAt: ttl ? Date.now() + ttl * 1000 : 0,
    });
  }

  leadCount() {
    return [...this.items.keys()].filter((key) => key.startsWith("lead:")).length;
  }
}

function request(body, method = "POST") {
  return new Request("https://getamicor.com/api/leads", {
    method,
    headers: { "Content-Type": "application/json", "CF-Connecting-IP": "203.0.113.10" },
    body: method === "POST" ? JSON.stringify(body) : undefined,
  });
}

function quote(overrides = {}) {
  return {
    name: "Jordan Hale",
    company: "North Star Transit",
    email: "jordan@northstar.example",
    phone: "555-0100",
    industry: "Operations",
    companySize: "11-50",
    product: "Business Services",
    message: "Need a cited research memo by Friday.",
    consent: true,
    source: "amicor-public-website-w8",
    ...overrides,
  };
}

async function post(env, body, deps) {
  const response = await handleLead(request(body), env, deps);
  const text = await response.text();
  return { status: response.status, body: text ? JSON.parse(text) : {} };
}

const tests = [];
function test(name, fn) {
  tests.push([name, fn]);
}

test("saves a synthetic quote and returns a reference without claiming email", async () => {
  const store = new MemoryKv();
  const result = await post({ AMICOR_LEADS: store }, quote());
  assert.equal(result.status, 202);
  assert.equal(result.body.ok, true);
  assert.equal(result.body.stored, true);
  assert.equal(result.body.duplicate, false);
  assert.match(result.body.referenceId, /^AMQ-[0-9A-F]{8}$/);
  assert.deepEqual(result.body.emailNotification, {
    attempted: false,
    sent: false,
    reason: "not_configured",
  });
  const saved = JSON.parse(await store.get(`lead:${result.body.referenceId}`));
  assert.equal(saved.email, "jordan@northstar.example");
  assert.equal(saved.message, "Need a cited research memo by Friday.");
  assert.equal(store.leadCount(), 1);
});

test("rejects the quote prompt template before writing", async () => {
  const store = new MemoryKv();
  const result = await post({ AMICOR_LEADS: store }, quote({
    message: "Project goal:\nDeliverables needed:\nApproximate volume:\nDeadline:",
  }));
  assert.equal(result.status, 400);
  assert.equal(result.body.error, "message_incomplete");
  assert.equal(result.body.stored, false);
  assert.equal(store.leadCount(), 0);
});

test("rejects missing fields and a bad email", async () => {
  const store = new MemoryKv();
  const missing = await post({ AMICOR_LEADS: store }, quote({ industry: "" }));
  assert.equal(missing.status, 400);
  assert.equal(missing.body.error, "missing_fields");
  const email = await post({ AMICOR_LEADS: store }, quote({ email: "not-an-email" }));
  assert.equal(email.status, 400);
  assert.equal(email.body.error, "invalid_email");
  assert.equal(store.leadCount(), 0);
});

test("does not confirm when the store write fails", async () => {
  const store = new MemoryKv();
  store.failPut = true;
  let webhookCalls = 0;
  const result = await post({ AMICOR_LEADS: store, LEAD_WEBHOOK_URL: "https://notify.example/lead" }, quote(), {
    fetchImpl: async () => {
      webhookCalls += 1;
      return new Response("ok", { status: 200 });
    },
  });
  assert.equal(result.status, 500);
  assert.equal(result.body.stored, false);
  assert.equal(result.body.error, "not_saved");
  assert.equal(result.body.emailNotification.attempted, false);
  assert.equal(webhookCalls, 0);
});

test("keeps the reference when notification fails after the save", async () => {
  const store = new MemoryKv();
  const result = await post({ AMICOR_LEADS: store, LEAD_WEBHOOK_URL: "https://notify.example/lead" }, quote(), {
    fetchImpl: async () => new Response("no", { status: 502 }),
  });
  assert.equal(result.status, 202);
  assert.equal(result.body.stored, true);
  assert.match(result.body.referenceId, /^AMQ-/);
  assert.equal(result.body.emailNotification.attempted, true);
  assert.equal(result.body.emailNotification.sent, false);
  assert.equal(result.body.emailNotification.reason, "webhook_failed");
  assert.equal(result.body.notified, false);
});

test("returns the same reference for a duplicate and does not write another lead", async () => {
  const store = new MemoryKv();
  const first = await post({ AMICOR_LEADS: store }, quote());
  const second = await post({ AMICOR_LEADS: store }, quote());
  assert.equal(second.status, 200);
  assert.equal(second.body.duplicate, true);
  assert.equal(second.body.stored, true);
  assert.equal(second.body.referenceId, first.body.referenceId);
  assert.equal(second.body.emailNotification.reason, "duplicate");
  assert.equal(store.leadCount(), 1);
});

test("does not confirm from a webhook when KV is missing", async () => {
  let webhookCalls = 0;
  const result = await post({ LEAD_WEBHOOK_URL: "https://notify.example/lead" }, quote(), {
    fetchImpl: async () => {
      webhookCalls += 1;
      return new Response("ok", { status: 200 });
    },
  });
  assert.equal(result.status, 503);
  assert.equal(result.body.stored, false);
  assert.equal(result.body.error, "lead_delivery_disabled");
  assert.equal(webhookCalls, 0);
});

let failed = 0;
for (const [name, fn] of tests) {
  try {
    await fn();
    console.log(`PASS ${name}`);
  } catch (err) {
    failed += 1;
    console.error(`FAIL ${name}`);
    console.error(err);
  }
}
console.log(`API_TESTS_PASSED=${tests.length - failed}`);
console.log(`API_TESTS_FAILED=${failed}`);
if (failed) process.exit(1);
