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


test("signed owner JWT reads only consented Growth inquiries",async()=>{
  const { generateKeyPairSync,sign }=await import("node:crypto");
  const {publicKey,privateKey}=generateKeyPairSync("rsa",{modulusLength:2048});
  const jwk=publicKey.export({format:"jwk"});
  jwk.kid="test-key";jwk.alg="RS256";
  const segment=x=>Buffer.from(JSON.stringify(x)).toString("base64url");
  const header=segment({alg:"RS256",kid:"test-key"});
  const now=Math.floor(Date.now()/1000);
  const payload=segment({iss:"https://example.cloudflareaccess.com",aud:["test-audience"],email:"owner@example.org",iat:now-5,exp:now+300});
  const input=header+"."+payload;
  const jwt=input+"."+sign("RSA-SHA256",Buffer.from(input),privateKey).toString("base64url");
  const oldFetch=globalThis.fetch;
  let lists=0;
  globalThis.fetch=async url=>{
    assert.equal(String(url),"https://example.cloudflareaccess.com/cdn-cgi/access/certs");
    return new Response(JSON.stringify({keys:[jwk]}),{status:200,headers:{"content-type":"application/json"}});
  };
  const env={
    GROWTH_ACCESS_DOMAIN:"https://example.cloudflareaccess.com",
    GROWTH_ACCESS_AUD:"test-audience",
    GROWTH_OWNER_EMAIL:"owner@example.org",
    AMICOR_LEADS:{
      list:async()=>{lists++;return {keys:[{name:"lead:2026-11-23T00:00:00Z:1"},{name:"lead:2026-11-23T00:00:00Z:2"},{name:"lead:2026-11-23T00:00:00Z:3"}],list_complete:true}},
      get:async key=>key.endsWith(":1")?{name:"Approved",product:"Nova Growth Agent",consent:true,email:"growth@example.org"}:
        key.endsWith(":2")?{name:"No consent",product:"Nova Growth Agent",consent:false}:
        {name:"Another product",product:"Nova Operations Agent",consent:true}
    }
  };
  try{
    const response=await onRequest({...req("GET",jwt),env});
    assert.equal(response.status,200);
    assert.equal(lists,1);
    const result=await response.json();
    assert.equal(result.rows.length,1);
    assert.equal(result.rows[0].name,"Approved");
    assert.equal(result.rows[0].product,"Nova Growth Agent");
    assert.equal(result.complete,true);
  }finally{globalThis.fetch=oldFetch;}
});
