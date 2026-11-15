// In-memory contract checks. No production data, email, payment, or network.
import assert from "node:assert/strict";
import { onRequest } from "../functions/api/leads.js";
globalThis.caches = { default: { async match(){ return null; }, async put(){} } };
globalThis.fetch = async () => { throw new Error("Network forbidden in this check"); };
const writes = [];
const store = { async put(key,value){ writes.push(JSON.parse(value)); } };
const lead = {name:"AMICOR Synthetic Check",company:"Synthetic Home Service",email:"scope-check@example.invalid",phone:"",industry:"Home services",companySize:"1-10",product:"Nova Operations Agent",message:"Free Scope Check — Inquiry Support\nApproximate number of inquiries: 25\nDesired output: tracker and drafts. SYNTHETIC: do not contact.",consent:true};
async function post(payload,env){ return onRequest({request:new Request("https://staging.invalid/api/leads",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}),env}); }
let r=await post(lead,{AMICOR_LEADS:store});
assert.equal(r.status,202);const receipt=await r.json();assert.equal(receipt.stored,true);assert.equal(receipt.notified,false);assert.equal(writes.length,1);assert.equal(writes[0].message,lead.message);
r=await post({...lead,consent:false},{AMICOR_LEADS:store});assert.equal(r.status,400);assert.equal(writes.length,1);
r=await post({...lead,email:"bad-address"},{AMICOR_LEADS:store});assert.equal(r.status,400);assert.equal(writes.length,1);
r=await post(lead,{});assert.equal(r.status,503);assert.equal((await r.json()).ok,false);
await assert.rejects(()=>post(lead,{AMICOR_LEADS:{async put(){throw new Error("storage unavailable");}}}),/storage unavailable/);assert.equal(writes.length,1);
console.log("5 inquiry contract checks passed: persisted request, consent, email, disabled delivery, failed storage. Synthetic memory only.");
