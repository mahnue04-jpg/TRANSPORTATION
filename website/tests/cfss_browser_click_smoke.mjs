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
const context={
 document:{getElementById:node,body:{appendChild(){}},createElement:()=>({click(){},remove(){}})},
 window:{print(){}}, console,Intl,Number,Math,String,Array,Object,Date,Error,JSON,SetTimeout:()=>{},
 setTimeout:()=>{},Blob:class{},URL:{createObjectURL:()=>"",revokeObjectURL(){}}
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
console.log("CFSS_CLICK_SMOKE_PASSED=17");
