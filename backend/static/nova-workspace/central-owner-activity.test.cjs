const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const script = fs.readFileSync(path.join(__dirname,"central-owner-activity.js"),"utf8");
const data = {work_opportunities:3, applications_needing_approval:2, follow_ups_due:1, active_engagements:4, active_tasks:5, deliverables_pending:6, owner_action_required:7};
function harness({auth=true,status=200,body=data,offline=false}={}) {
  let click;
  const button={disabled:false,addEventListener(event,fn){assert.equal(event,"click");click=fn;}};
  const output={textContent:""};
  const calls=[];
  vm.runInNewContext(script,{document:{getElementById:id=>id==="central-activity-refresh"?button:id==="central-activity-output"?output:null},window:{AmiCorSession:{getAuthHeaders:()=>auth?{Authorization:"Bearer synthetic"}:{}}},fetch:async(url,opts)=>{calls.push({url,opts});if(offline)throw Error("offline");return {status,ok:status===200,json:async()=>body};}});
  return {button,output,calls,click:()=>click()};
}
test("no token: no network",async()=>{const h=harness({auth:false});await h.click();assert.equal(h.calls.length,0);assert.match(h.output.textContent,/Sign in/);});
test("owner summary is same-origin GET and accurately labeled",async()=>{const h=harness();await h.click();assert.equal(h.calls.length,1);assert.equal(h.calls[0].url,"/api/nova/work/today-summary");assert.equal(h.calls[0].opts.method,"GET");assert.equal(h.calls[0].opts.redirect,"error");assert.match(h.output.textContent,/Tracked opportunities: 3/);assert.match(h.output.textContent,/may include simulated/);assert.equal(h.button.disabled,false);});
for(const status of [401,403,404,503])test("denied or unavailable "+status,async()=>{const h=harness({status});await h.click();assert.doesNotMatch(h.output.textContent,/Tracked opportunities:/);assert.equal(h.button.disabled,false);});
test("invalid or offline data never becomes zero",async()=>{for(const opts of [{body:{...data,active_tasks:-1}},{body:{}},{offline:true}]){const h=harness(opts);await h.click();assert.match(h.output.textContent,/No counts shown/);assert.equal(h.button.disabled,false);}});


const handoffData = {synthetic:true,mode:"read_only_in_memory_demo",accepted_count:4,completed:true,live_dispatch:false,persistent_storage_connected:false,real_approval_verified:false};
function handoffHarness({auth=true,status=200,body=handoffData,offline=false,switchSession=false}={}) {
  const calls=[], handlers={}, elements={};
  let token=auth?"Bearer synthetic":undefined;
  for(const id of ["central-activity-refresh","central-handoff-refresh"]) {
    elements[id]={disabled:false,addEventListener(event,fn){assert.equal(event,"click");handlers[id]=fn;}};
  }
  for(const id of ["central-activity-output","central-handoff-output"]) elements[id]={textContent:""};
  vm.runInNewContext(script,{
    document:{getElementById:id=>elements[id]||null},
    window:{AmiCorSession:{getAuthHeaders:()=>token?{Authorization:token}:{}}},
    fetch:async(url,opts)=>{
      calls.push({url,opts});
      if(offline)throw Error("offline");
      return {status,ok:status===200,json:async()=>{if(switchSession)token="Bearer other";return body;}};
    }
  });
  return {calls,output:elements["central-handoff-output"],button:elements["central-handoff-refresh"],click:()=>handlers["central-handoff-refresh"]()};
}
test("handoff status uses authenticated same-origin GET",async()=>{
  const h=handoffHarness();await h.click();
  assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].url,"/api/nova/work/agent-handoff-rehearsal");
  assert.equal(h.calls[0].opts.method,"GET");
  assert.equal(h.calls[0].opts.headers.Authorization,"Bearer synthetic");
  assert.equal(h.calls[0].opts.cache,"no-store");
  assert.equal(h.calls[0].opts.redirect,"error");
  assert.match(h.output.textContent,/Synthetic rehearsal: 4 of 4/);
  assert.match(h.output.textContent,/no real approvals or live dispatch/);
  assert.equal(h.button.disabled,false);
});
test("handoff without token makes no request",async()=>{
  const h=handoffHarness({auth:false});await h.click();
  assert.equal(h.calls.length,0);assert.match(h.output.textContent,/Sign in/);
});
for(const status of [401,403,404,503])test("handoff denied or unavailable "+status,async()=>{
  const h=handoffHarness({status});await h.click();
  assert.doesNotMatch(h.output.textContent,/4 of 4/);assert.equal(h.button.disabled,false);
});
test("handoff rejects malformed, live or changed-session responses",async()=>{
  for(const opts of [{body:{}},{body:{...handoffData,synthetic:false}},{body:{...handoffData,live_dispatch:true}},{body:{...handoffData,real_approval_verified:true}},{body:{...handoffData,accepted_count:3}},{switchSession:true},{offline:true}]){
    const h=handoffHarness(opts);await h.click();
    assert.match(h.output.textContent,/No status shown/);assert.equal(h.button.disabled,false);
  }
});


test("persisted status accurately displays every valid stage",async()=>{
  for(let count=0;count<=4;count++){
    const h=handoffHarness({body:{...handoffData,mode:"read_only_persisted_rehearsal",persistent_storage_connected:true,accepted_count:count,completed:count===4}});
    await h.click();assert.match(h.output.textContent,new RegExp("Synthetic rehearsal: "+count+" of 4"));
    assert.match(h.output.textContent,/Read-only persisted rehearsal/);
  }
});
test("persisted status rejects inconsistent count, completion and storage flags",async()=>{
  const base={...handoffData,mode:"read_only_persisted_rehearsal",persistent_storage_connected:true};
  for(const body of [{...base,accepted_count:2},{...base,accepted_count:5},{...base,accepted_count:-1},{...base,persistent_storage_connected:false},{...base,completed:false}]){
    const h=handoffHarness({body});await h.click();assert.match(h.output.textContent,/No status shown/);
  }
});
