import assert from "node:assert/strict";
import test from "node:test";
import { normalizeWebsiteLeadEntry, normalizeWebsiteLeadEntries } from "../lib/website-lead-normalize.mjs";

const base = { receivedAt: "2026-11-14T10:00:00.000Z", name: "Test Customer", email: "TEST@example.com", company: "Example LLC", product: "Nova Operations Agent", message: "CSV cleanup", consent: true };
const legacy = { key: "lead:2026-11-14T10:00:00.000Z:1234", value: JSON.stringify(base) };
test("legacy lead preserves exact source key and normalizes email", () => {
  const x = normalizeWebsiteLeadEntry(legacy);
  assert.equal(x.source_key, legacy.key);
  assert.equal(x.email, "test@example.com");
  assert.equal(x.reference_id, null);
  assert.equal(x.status, "needs_review");
});
test("AMQ lead retains reference", () => {
  const x = normalizeWebsiteLeadEntry({ key: "lead:AMQ-20261114-ABCD", value: JSON.stringify(base) });
  assert.equal(x.reference_id, "AMQ-20261114-ABCD");
});
test("dedupe and unrelated keys are ignored", () => {
  assert.equal(normalizeWebsiteLeadEntry({ key: "dedupe:a", value: JSON.stringify(base) }), null);
  assert.equal(normalizeWebsiteLeadEntry({ key: "other:a", value: JSON.stringify(base) }), null);
});
test("bad JSON, missing fields, invalid dates and oversized input fail closed", () => {
  assert.equal(normalizeWebsiteLeadEntry({ key: "lead:x", value: "{" }), null);
  assert.equal(normalizeWebsiteLeadEntry({ key: "lead:x", value: JSON.stringify({ ...base, email: "" }) }), null);
  assert.equal(normalizeWebsiteLeadEntry({ key: "lead:x", value: JSON.stringify({ ...base, receivedAt: "wrong" }) }), null);
  assert.equal(normalizeWebsiteLeadEntry({ key: "lead:x", value: "x".repeat(16001) }), null);
});
test("missing consent is never converted to affirmative", () => {
  assert.equal(normalizeWebsiteLeadEntry({ key: "lead:x", value: JSON.stringify({ ...base, consent: false }) }).consent, false);
});
test("repeat source keys never appear twice", () => {
  assert.equal(normalizeWebsiteLeadEntries([legacy, legacy]).length, 1);
});
test("synthetic records are labeled and do not become revenue", () => {
  const x = normalizeWebsiteLeadEntry({ key: "lead:AMQ-1", value: JSON.stringify({ ...base, is_synthetic: true }) });
  assert.equal(x.is_synthetic, true);
  assert.equal("revenue" in x, false);
});
