// Security regression for the AMICOR Growth Cloudflare Pages inbox.
// Run: node --test website/tests/growth_owner_inbox.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const js = await readFile(new URL("../functions/nova-growth/owner/api.js", import.meta.url), "utf8");
const { onRequest } = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));
function req(method="GET",header="") {
  const headers = new Headers();
  if (header) headers.set("Cf-Access-Jwt-Assertion",header);
  return {request:new Request("https://getamicor.com/nova-growth/owner/api",{method,headers})};
}
test("public visitors never read lead KV without Cloudflare Access configuration",async()=>{
  let reads=0;
  const env={AMICOR_LEADS:{list:async()=>{reads++;return {keys:[],list_complete:true}}}};
  const response=await onRequest({...req(),env});
  assert.equal(response.status,503);
  assert.equal(reads,0);
  assert.equal((await response.json()).ok,false);
  assert.equal(response.headers.get("cache-control"),"private, no-store, max-age=0");
});
test("owner config without a signed Access JWT still blocks KV",async()=>{
  let reads=0;
  const env={GROWTH_ACCESS_DOMAIN:"https://example.cloudflareaccess.com",GROWTH_ACCESS_AUD:"aud-example",GROWTH_OWNER_EMAIL:"owner@example.org",AMICOR_LEADS:{list:async()=>{reads++;}}};
  const response=await onRequest({...req(),env});
  assert.equal(response.status,403);
  assert.equal(reads,0);
});
test("a forged JWT cannot bypass authentication",async()=>{
  let reads=0;
  const env={GROWTH_ACCESS_DOMAIN:"https://example.cloudflareaccess.com",GROWTH_ACCESS_AUD:"aud-example",GROWTH_OWNER_EMAIL:"owner@example.org",AMICOR_LEADS:{list:async()=>{reads++;}}};
  const segment=x=>Buffer.from(JSON.stringify(x)).toString("base64url");
  const jwt=segment({alg:"none",kid:"forged"})+"."+segment({email:"owner@example.org",iss:"https://example.cloudflareaccess.com",aud:["aud-example"],exp:Math.floor(Date.now()/1000)+300})+"."+segment("bad");
  const response=await onRequest({...req("GET",jwt),env});
  assert.equal(response.status,403);
  assert.equal(reads,0);
});
test("the inbox rejects write methods without accessing KV",async()=>{
  const response=await onRequest({...req("POST"),env:{}});
  assert.equal(response.status,405);
});
