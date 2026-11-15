import assert from "node:assert/strict";
import test from "node:test";
import { getOwnerWebsiteInquiries } from "../lib/website-lead-owner-service.mjs";

const rec = JSON.stringify({receivedAt:"2026-11-14T12:00:00Z",name:"Synthetic Lead",email:"sample@example.com",consent:true,is_synthetic:true});
function kv() {
  let calls = 0;
  return { get calls() { return calls; },
    async list() { calls++; return { keys: [{name:"lead:AMQ-TEST"}], list_complete:true }; },
    async get() { calls++; return rec; }
  };
}
const valid = { authenticated:true, role:"admin", userId:"owner-1", tenantId:"tenant-1" };
const invoke = (principal, store=kv()) => getOwnerWebsiteInquiries({
  resolvePrincipal: async () => principal, session: "trusted-session",
  kv: store, tenantId:"tenant-1"
});
test("authenticated admin sees normalized synthetic inquiry", async () => {
  const r = await invoke(valid);
  assert.equal(r.status,200);
  assert.equal(r.body.inquiries[0].is_synthetic,true);
});
test("missing verifier fails unavailable without KV reads", async () => {
  const store=kv();
  const r=await getOwnerWebsiteInquiries({kv:store,tenantId:"tenant-1"});
  assert.equal(r.status,503);
  assert.equal(store.calls,0);
});
test("unauthenticated access denies before KV reads", async () => {
  const store=kv();
  const r=await invoke(null,store);
  assert.equal(r.status,401);
  assert.equal(store.calls,0);
});
test("non-owner access denies before KV reads", async () => {
  const store=kv();
  const r=await invoke({...valid,role:"member"},store);
  assert.equal(r.status,403);
  assert.equal(store.calls,0);
});
test("cross-tenant access denies before KV reads", async () => {
  const store=kv();
  const r=await invoke({...valid,tenantId:"other"},store);
  assert.equal(r.status,403);
  assert.equal(store.calls,0);
});
test("missing tenant ID denies before KV reads", async () => {
  const store=kv();
  const r=await getOwnerWebsiteInquiries({resolvePrincipal:async()=>valid,session:"x",kv:store,tenantId:""});
  assert.equal(r.status,403);
  assert.equal(store.calls,0);
});
test("verifier error denies before KV reads", async () => {
  const store=kv();
  const r=await getOwnerWebsiteInquiries({resolvePrincipal:async()=>{throw Error("internal");},session:"x",kv:store,tenantId:"tenant-1"});
  assert.equal(r.status,401);
  assert.equal(store.calls,0);
});

test("unsupported owner label is rejected (backend uses explicit admin roles)", async () => {
  const store=kv();
  const r=await invoke({...valid,role:"owner"},store);
  assert.equal(r.status,403);
  assert.equal(store.calls,0);
});
test("missing authenticated user ID is rejected", async () => {
  const store=kv();
  const r=await invoke({...valid,userId:""},store);
  assert.equal(r.status,403);
  assert.equal(store.calls,0);
});
test("super admin support role is authorized with tenant context", async () => {
  const r=await invoke({...valid,role:"super_admin_support"});
  assert.equal(r.status,200);
});
