"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const html = fs.readFileSync(path.join(__dirname,"index.html"),"utf8");
const code = fs.readFileSync(path.join(__dirname,"growth-website-inquiries.js"),"utf8");
test("manually triggered owner status panel is discoverable",()=>{
  assert.match(html,/id="growth-website-inquiries-refresh"/);
  assert.match(html,/id="growth-website-inquiries-result"/);
  assert.match(html,/growth-website-inquiries\.js/);
  assert.match(code,/method: "GET"/);
  assert.match(code,/data.synthetic_handoff_enabled === true/);
});
function harness({token="example",response={state:"unavailable",inquiries:[],complete:false},status=200}={}){
  let click;
  const calls=[];
  const button={disabled:false,addEventListener:(type,handler)=>{if(type==="click")click=handler;}};
  const output={textContent:""};
  const session={getAccessToken:()=>token,getAuthHeaders:()=>({Authorization:"Bearer "+token})};
  const context={
    document:{getElementById:(id)=>id==="growth-website-inquiries-refresh"?button:id==="growth-website-inquiries-result"?output:null},
    window:{AmiCorSession:session},
    fetch:async(url,opts)=>{calls.push({url,opts});return {status,ok:status>=200&&status<300,json:async()=>response};}
  };
  vm.runInNewContext(code,context);
  return {click:()=>click(),button,output,calls};
}
test("signed-out session never fetches customer data",async()=>{
  const h=harness({token:""});
  await h.click();
  assert.equal(h.calls.length,0);
  assert.match(h.output.textContent,/Sign in/);
});
test("unavailable is not represented as zero customers",async()=>{
  const h=harness();
  await h.click();
  assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].opts.method,"GET");
  assert.equal(h.calls[0].opts.headers.Authorization,"Bearer example");
  assert.match(h.output.textContent,/not connected/);
  assert.match(h.output.textContent,/not a count of zero/);
});
test("synthetic snapshot is labeled separately from CRM",async()=>{
  const h=harness({response:{state:"available",complete:true,inquiries:[
    {source_system:"cloudflare_amicor_leads",source_key:"lead:AMQ-1",is_synthetic:true},
    {source_system:"cloudflare_amicor_leads",source_key:"lead:AMQ-2",is_synthetic:false}
  ]}});
  await h.click();
  assert.match(h.output.textContent,/2 records \(1 synthetic\)/);
  assert.match(h.output.textContent,/not CRM contacts/);
  assert.doesNotMatch(h.output.textContent,/paid customers: 2/);
});
test("stale, forbidden, and malformed snapshots disclose nothing",async()=>{
  for(const opts of [
    {response:{state:"stale",inquiries:[],complete:false}},
    {status:403},
    {response:{state:"available",complete:true,inquiries:[{source_system:"wrong",source_key:"lead:x"}]}}
  ]){
    const h=harness(opts);
    await h.click();
    assert.doesNotMatch(h.output.textContent,/Website inquiry snapshot:/);
    assert.equal(h.button.disabled,false);
  }
});

test("owner sees source reference, requested service and synthetic label", async () => {
  const h=harness({response:{state:"available",complete:true,inquiries:[
    {source_system:"cloudflare_amicor_leads",source_key:"lead:AMQ-TEST",
     reference_id:"AMQ-TEST",product:"Nova Operations Agent",
     name:"Synthetic Applicant",consent:true,is_synthetic:true}
  ]}});
  await h.click();
  assert.match(h.output.textContent,/AMQ-TEST/);
  assert.match(h.output.textContent,/Nova Operations Agent/);
  assert.match(h.output.textContent,/Synthetic Applicant/);
  assert.match(h.output.textContent,/\[SYNTHETIC\]/);
  assert.match(h.output.textContent,/consent recorded/);
  assert.doesNotMatch(h.output.textContent,/Completed jobs: 1/);
});
