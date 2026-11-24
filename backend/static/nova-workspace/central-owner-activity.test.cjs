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
  vm.runInNewContext(script,{document:{getElementById:id=>id==="central-activity-refresh"?button:output},window:{AmiCorSession:{getAuthHeaders:()=>auth?{Authorization:"Bearer synthetic"}:{}}},fetch:async(url,opts)=>{calls.push({url,opts});if(offline)throw Error("offline");return {status,ok:status===200,json:async()=>body};}});
  return {button,output,calls,click:()=>click()};
}
test("no token: no network",async()=>{const h=harness({auth:false});await h.click();assert.equal(h.calls.length,0);assert.match(h.output.textContent,/Sign in/);});
test("owner summary is same-origin GET and accurately labeled",async()=>{const h=harness();await h.click();assert.equal(h.calls.length,1);assert.equal(h.calls[0].url,"/api/nova/work/today-summary");assert.equal(h.calls[0].opts.method,"GET");assert.equal(h.calls[0].opts.redirect,"error");assert.match(h.output.textContent,/Tracked opportunities: 3/);assert.match(h.output.textContent,/may include simulated/);assert.equal(h.button.disabled,false);});
for(const status of [401,403,404,503])test("denied or unavailable "+status,async()=>{const h=harness({status});await h.click();assert.doesNotMatch(h.output.textContent,/Tracked opportunities:/);assert.equal(h.button.disabled,false);});
test("invalid or offline data never becomes zero",async()=>{for(const opts of [{body:{...data,active_tasks:-1}},{body:{}},{offline:true}]){const h=harness(opts);await h.click();assert.match(h.output.textContent,/No counts shown/);assert.equal(h.button.disabled,false);}});
