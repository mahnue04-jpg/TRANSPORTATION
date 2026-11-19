'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeWebsiteLead, normalizeWebsiteLeadPage } = require('./website-lead-adapter.cjs');
const payload = {receivedAt:'2026-11-14T21:00:00.000Z',name:'AMICOR QA Test',company:'AMICOR',email:'qa@example.com',product:'Business Services',message:'INTERNAL TEST ONLY',consent:true};
const oldKey = 'lead:2026-11-14T21:00:00.000Z:12345678-1234-1234-1234-123456789abc';
test('legacy key produces reviewed synthetic inquiry',()=>{
 const x=normalizeWebsiteLead(oldKey,JSON.stringify(payload),{trustedSyntheticFixture:true});
 assert.equal(x.source_key,oldKey);assert.equal(x.reference_id,null);assert.equal(x.is_synthetic,true);assert.equal(x.status,'needs_owner_review');
});
test('new AMQ format produces stable reference',()=>{
 const x=normalizeWebsiteLead('lead:AMQ-AB12CD34',{...payload,referenceId:'AMQ-AB12CD34'});
 assert.equal(x.reference_id,'AMQ-AB12CD34');
});
test('dedupe index and malformed entries ignored',()=>{
 assert.equal(normalizeWebsiteLead('dedupe:whatever',payload),null);
 assert.equal(normalizeWebsiteLead('lead:AMQ-AB12CD34','bad-json'),null);
 assert.equal(normalizeWebsiteLead('lead:AMQ-AB12CD34',{...payload,consent:false}),null);
});
test('repeated identical KV key is deduplicated',()=>{
 assert.equal(normalizeWebsiteLeadPage([{key:oldKey,value:payload},{key:oldKey,value:payload}]).length,1);
});
test('unavailable input is not silently treated as zero',()=>{
 assert.throws(()=>normalizeWebsiteLeadPage(null),TypeError);
});

test('customer-controlled test words cannot mark an untrusted inquiry synthetic',()=>{
 const x=normalizeWebsiteLead(oldKey,JSON.stringify(payload));
 assert.equal(x.is_synthetic,false);
});
