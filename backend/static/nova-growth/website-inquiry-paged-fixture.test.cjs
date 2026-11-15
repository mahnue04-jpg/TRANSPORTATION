'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createFixturePagedSource}=require('./website-inquiry-paged-fixture.cjs');
const {loadWebsiteInquiries}=require('./website-inquiry-owner-service.cjs');
const owner={authenticated:true,role:'owner',organization_id:'amicor'};
const lead=(name)=>JSON.stringify({receivedAt:'2026-11-14T21:00:00Z',name,company:'Fictional Co',email:'qa@example.invalid',message:'INTERNAL TEST ONLY',consent:true});
const k1='lead:AMQ-AB12CD34',k2='lead:AMQ-AB12CD35';
test('two pages produce complete duplicate-free normalized records',async()=>{
 const calls=[];
 const kv={
  list:async ({cursor})=>cursor?{keys:[{name:k1},{name:k2}],list_complete:true}:{keys:[{name:k1}],list_complete:false,cursor:'next'},
  get:async key=>{calls.push(key);return lead(key===k1?'Synthetic First':'Synthetic Second');}
 };
 const result=await loadWebsiteInquiries({principal:owner,organizationId:'amicor',source:createFixturePagedSource(kv)});
 assert.equal(result.status,'ok');assert.equal(result.count,2);
 assert.deepEqual(calls,[k1,k2]);
});
test('refuse truncated listing without claiming zero leads',async()=>{
 const kv={list:async()=>({keys:[],list_complete:false,cursor:'repeat'}),get:async()=>lead('Synthetic')};
 const result=await loadWebsiteInquiries({principal:owner,organizationId:'amicor',source:createFixturePagedSource(kv)});
 assert.equal(result.status,'unavailable');assert.equal(result.inquiries,null);
});
test('disappearing key fails closed',async()=>{
 const kv={list:async()=>({keys:[{name:k1}],list_complete:true}),get:async()=>null};
 const result=await loadWebsiteInquiries({principal:owner,organizationId:'amicor',source:createFixturePagedSource(kv)});
 assert.equal(result.status,'unavailable');assert.equal(result.inquiries,null);
});
test('owner denied before reading KV fixture',async()=>{
 let calls=0;
 const kv={list:async()=>{calls++;return {keys:[],list_complete:true};},get:async()=>null};
 await assert.rejects(loadWebsiteInquiries({principal:null,organizationId:'amicor',source:createFixturePagedSource(kv)}),{status:403});
 assert.equal(calls,0);
});
test('non-lead KV keys ignored and not fetched',async()=>{
 const kv={list:async()=>({keys:[{name:'dedupe:123'},{name:k1}],list_complete:true}),get:async key=>{assert.equal(key,k1);return lead('Synthetic');}};
 const result=await loadWebsiteInquiries({principal:owner,organizationId:'amicor',source:createFixturePagedSource(kv)});
 assert.equal(result.count,1);
});
