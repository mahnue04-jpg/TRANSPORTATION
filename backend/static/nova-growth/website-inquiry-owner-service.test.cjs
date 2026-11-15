'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadWebsiteInquiries } = require('./website-inquiry-owner-service.cjs');
const owner = { authenticated:true, role:'owner', organization_id:'amicor' };
const record = { receivedAt:'2026-11-14T21:00:00.000Z', name:'AMICOR QA Test', company:'AMICOR', email:'qa@example.com', message:'INTERNAL TEST ONLY', consent:true };
const key = 'lead:AMQ-AB12CD34';
test('owner receives synthetic inquiry once from injected fixture', async () => {
  const source = { list:async () => ({complete:true,entries:[{key,value:record},{key,value:record}]}) };
  const result = await loadWebsiteInquiries({principal:owner,organizationId:'amicor',source});
  assert.equal(result.status,'ok');
  assert.equal(result.count,1);
  assert.equal(result.inquiries[0].is_synthetic,true);
});
test('anonymous access is denied before source access', async () => {
  let reads = 0;
  const source = {list:async ()=>{reads++;return {complete:true,entries:[]};}};
  await assert.rejects(loadWebsiteInquiries({principal:null,organizationId:'amicor',source}), {status:403});
  assert.equal(reads,0);
});
test('cross-tenant owner access is denied', async () => {
  await assert.rejects(loadWebsiteInquiries({principal:owner,organizationId:'other',source:{list:async()=>({complete:true,entries:[]})}}), {status:403});
});
test('missing source is unavailable, never zero leads', async () => {
  const result = await loadWebsiteInquiries({principal:owner,organizationId:'amicor'});
  assert.equal(result.status,'unavailable');assert.equal(result.inquiries,null);
});
test('incomplete pages fail closed rather than hiding further leads', async () => {
  const result = await loadWebsiteInquiries({principal:owner,organizationId:'amicor',source:{list:async()=>({complete:false,entries:[]})}});
  assert.equal(result.status,'unavailable');assert.equal(result.inquiries,null);
});
test('read failure hides internal details', async () => {
  const result = await loadWebsiteInquiries({principal:owner,organizationId:'amicor',source:{list:async()=>{throw Error('SECRET');}}});
  assert.equal(result.reason,'source_read_failed');assert.equal(JSON.stringify(result).includes('SECRET'),false);
});
