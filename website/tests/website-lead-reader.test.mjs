import assert from "node:assert/strict";
import test from "node:test";
import { readWebsiteInquiries } from "../lib/website-lead-reader.mjs";
const record = JSON.stringify({ receivedAt: "2026-11-14T12:00:00Z", name: "Sample", email: "sample@example.com", consent: true });
function fixture(pages, values) {
  let index = 0;
  return { async list() { return pages[index++]; }, async get(key) { return values[key] ?? null; } };
}
test("reader returns distinct inquiries across paginated KV keys", async () => {
  const store = fixture([
    { keys: [{ name: "lead:legacy" }], list_complete: false, cursor: "next" },
    { keys: [{ name: "lead:AMQ-1234" }, { name: "lead:legacy" }], list_complete: true },
  ], { "lead:legacy": record, "lead:AMQ-1234": record });
  const result = await readWebsiteInquiries(store);
  assert.equal(result.state, "available");
  assert.equal(result.complete, true);
  assert.equal(result.inquiries.length, 2);
});
test("missing binding is unavailable, never zero-ready", async () => {
  const result = await readWebsiteInquiries(null);
  assert.deepEqual(result, { state: "unavailable", inquiries: [], complete: false });
});
test("list failures do not return partial customer data", async () => {
  const store = { async list() { throw Error("secret connection failed"); }, async get() { return record; } };
  const result = await readWebsiteInquiries(store);
  assert.equal(result.state, "unavailable");
  assert.deepEqual(result.inquiries, []);
});
test("incomplete pagination explicitly reports stale", async () => {
  const store = fixture([{ keys: [{name:"lead:one"}], list_complete: false, cursor:"another" }], { "lead:one": record });
  const result = await readWebsiteInquiries(store, { maxPages: 1 });
  assert.equal(result.state, "stale");
  assert.equal(result.complete, false);
  assert.deepEqual(result.inquiries, []);
});
test("repeated cursor fails closed rather than looping", async () => {
  const store = fixture([
    { keys: [], list_complete: false, cursor: "same" },
    { keys: [], list_complete: false, cursor: "same" }
  ], {});
  const result = await readWebsiteInquiries(store);
  assert.equal(result.state, "stale");
});
test("unrelated index entries never cause get calls", async () => {
  let reads = 0;
  const store = { async list() { return { keys: [{name:"dedupe:secret"}, {name:"lead:one"}], list_complete:true }; }, async get() { reads++; return record; } };
  const result = await readWebsiteInquiries(store);
  assert.equal(reads, 1);
  assert.equal(result.inquiries.length, 1);
});
