// Run the real CFSS application handlers against a minimal local DOM.
// This exercises the same "Load fictional example" click that failed in the browser.
// No outside network, no simulated payments and no customer data.
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
const html=fs.readFileSync("website/cfss-copilot/index.html","utf8");
const css=fs.readFileSync("website/cfss-copilot/style.css","utf8");
const script=fs.readFileSync("website/cfss-copilot/app.js","utf8");
assert.match(html,/<link rel="stylesheet" href="\.\/style\.css">/);
assert.match(html,/<script src="\.\/app\.js" defer><\/script>/);
assert.match(html,/script-src 'self'; style-src 'self'/);
assert(css.includes(".layout") && css.includes(".fieldgrid"),"CSS layout is present");
const nodes=new Map();
const formFields=[...html.matchAll(/<input\b[^>]*\bid="([^"]+)"[^>]*>/g)];
for(const match of formFields){
 const src=match[0], id=match[1];
 const val=src.match(/\bvalue="([^"]*)"/)?.[1]??"";
 nodes.set(id,{id,value:val,min:src.match(/\bmin="([^"]*)"/)?.[1]??"",
 max:src.match(/\bmax="([^"]*)"/)?.[1]??"",step:src.match(/\bstep="([^"]*)"/)?.[1]??"",
 hidden:false,style:{},textContent:"",
 listeners:{},
 addEventListener(type,fn){this.listeners[type]=fn;},
 closest(){return {textContent:id};},
 reset(){this.value="";}});
 const field=nodes.get(id);
 // Real DOM <input>.value coerces assignments to strings.
 let currentValue=field.value;
 Object.defineProperty(field,"value",{get(){return currentValue;},set(next){currentValue=String(next);}});
}
function node(id){
 if(!nodes.has(id))nodes.set(id,{id,value:"",hidden:false,className:"",textContent:"",
 listeners:{},addEventListener(type,fn){this.listeners[type]=fn;},closest(){return{textContent:id}}});
 return nodes.get(id);
}
const form=node("budgetForm");
form.requestSubmit=function(){this.listeners.submit({preventDefault(){}});};
form.reset=function(){for(const f of nodes.values()){if(typeof f.value==="string")f.value="";}};
let lastBlob=null, downloadClicks=0, pickerClicks=0;
node("restoreFile").click=function(){pickerClicks++;};
const context={
 document:{getElementById:node,body:{appendChild(){}},createElement:()=>({click(){downloadClicks++;},remove(){}})},
 window:{print(){}}, console,Intl,Number,Math,String,Array,Object,Date,Error,JSON,
 setTimeout:()=>{},Blob:class {constructor(parts,opts){this.parts=parts;this.type=opts?.type;lastBlob=this;}},
 URL:{createObjectURL:()=> "blob:offline-smoke-test",revokeObjectURL(){}}
};
vm.runInNewContext(script,context,{timeout:2000});
assert.equal(typeof node("example").listeners.click,"function","Example button handler is registered");
node("example").listeners.click();
assert.equal(node("budget").value,"48000");
assert.equal(node("months").value,"12");
assert.equal(node("elapsed").value,"3");
assert.equal(node("spent").value,"9500");
assert.equal(node("wage").value,"20");
assert.equal(node("hours").value,"30");
assert.equal(node("burden").value,"17");
assert.equal(node("other").value,"200");
assert.equal(node("onetime").value,"450");
assert.equal(node("results").hidden,false,"Budget outlook becomes visible; error="+node("error").textContent);
assert.equal(node("error").textContent,"","Example must calculate without an error");
assert.equal(node("rBudget").textContent,"$48,000.00");
assert.equal(node("rMonths").textContent,"9");
assert.equal(node("rMonthly").textContent,"$3,242.00");
assert.equal(node("rProjected").textContent,"$39,128.00");
assert.equal(node("rVariance").textContent,"$8,872.00");
assert.equal(node("demoTag").hidden,false);
assert.match(node("fmsReconcile").textContent,/match the entered spent-to-date total/);
// Confirm the real Save plan handler creates a local JSON artifact.
assert.equal(typeof node("savePlan").listeners.click,"function");
node("savePlan").listeners.click();
assert(lastBlob,"Saving must create a JSON Blob");
assert.equal(downloadClicks,1,"Saving must initiate one local download");
const saved=JSON.parse(lastBlob.parts.join(""));
assert.equal(saved.kind,"amicor-cfss-plan");
assert.equal(saved.version,1);
assert.equal(saved.fictionalExample,true);
assert.equal(saved.fields.budget,48000);
assert.equal(saved.fields.fms1,3200);
assert.equal(saved.fields.fms2,3100);
assert.equal(saved.fields.fms3,3200);
assert.equal(saved.fields.fms4,null);
assert.equal(saved.fields.altHours,28);
// Confirm the custom chooser button works but the native chooser remains hidden.
assert.match(css,/\[hidden\]\s*\{display:none!important\}/);
node("restoreBtn").listeners.click();
assert.equal(pickerClicks,1,"Custom restore button opens the native chooser");
// Restore a saved plan after resetting and verify the financial outputs recalculate.
node("reset").listeners.click();
assert.equal(node("results").hidden,true,"Reset hides the budget outlook");
const fileInput=node("restoreFile");
fileInput.files=[{size:JSON.stringify(saved).length,text:async()=>JSON.stringify(saved)}];
await fileInput.listeners.change.call(fileInput);
assert.equal(node("error").textContent,"","Restoring valid JSON should not error");
assert.equal(node("results").hidden,false,"Restored plan is calculated");
assert.equal(node("rProjected").textContent,"$39,128.00");
assert.equal(node("rVariance").textContent,"$8,872.00");
assert.equal(node("fms1").value,"3200");
assert.equal(node("fms3").value,"3200");
assert.equal(node("altHours").value,"28");
assert.equal(fileInput.value,"","Input resets so the same saved file can be selected again");
// Reject malformed files without replacing the existing valid inputs.
fileInput.files=[{size:40,text:async()=> '{"kind":"invalid", "version":1}'}];
await fileInput.listeners.change.call(fileInput);
assert.match(node("error").textContent,/Could not restore plan/);
assert.equal(node("budget").value,"48000","Invalid JSON must not overwrite existing plan");
console.log("CFSS_CLICK_SMOKE_PASSED=35");
