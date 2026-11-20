(function(){
"use strict";
var form=document.getElementById("budgetForm");
var el=function(id){return document.getElementById(id);};
var current=null;
var exampleActive=false;
var money=function(n){return new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",minimumFractionDigits:2,maximumFractionDigits:2}).format(n);};
var round=function(n){return Math.round((n+Number.EPSILON)*100)/100;};
var read=function(id,mandatory){var f=el(id),str=f.value.trim();if(!str){if(mandatory)throw new Error("Enter "+f.closest("label").textContent.trim().replace(/\s+/g," ")+".");return null;}var v=Number(str);if(!Number.isFinite(v)||v<Number(f.min||0)||(f.max&&v>Number(f.max))||(f.step==="1"&&!Number.isInteger(v)))throw new Error("Check the value for "+f.closest("label").textContent.trim().replace(/\s+/g," ")+".");return v;};
var s=function(id,value){el(id).textContent=value;};
function calculate(values){
 var monthsLeft=values.months-values.elapsed;
 if(monthsLeft<0)throw new Error("Elapsed months cannot exceed plan months.");
 var baselineWages=values.wage*values.hours*52/12;
 var employer=baselineWages*values.burden/100;
 var monthly=baselineWages+employer+values.other;
 var future=monthly*monthsLeft+values.onetime;
 var projected=values.spent+future;
 var variance=values.budget-projected;
 // This is a budgeting comparison, NOT a CFSS authorization or a promise
 // that service units and worker hours have been approved.
 var leftoverForWages=values.budget-values.spent-values.onetime-values.other*monthsLeft;
 var hourlyCost=values.wage*(1+values.burden/100);
 var maxHours=null;
 if(monthsLeft>0&&hourlyCost>0){
   maxHours=Math.max(0,Math.min(168,Math.floor(Math.max(0,leftoverForWages)/(hourlyCost*(52/12)*monthsLeft)*4)/4));
 }
 var monthlyEntries=Array.isArray(values.fmsMonths)?values.fmsMonths:[];
 var recordedCount=0,recordedTotal=0,unexpectedCount=0;
 for(var m=0;m<monthlyEntries.length;m++){
  if(monthlyEntries[m]!==null&&monthlyEntries[m]!==undefined){
   if(m>=values.elapsed)unexpectedCount++;
   else{recordedCount++;recordedTotal+=monthlyEntries[m];}
  }
 }
 var allExpectedReported=values.elapsed>0&&recordedCount===values.elapsed&&unexpectedCount===0;
 var fmsDiff=allExpectedReported?Math.round((recordedTotal-values.spent)*100)/100:null;
 var fmsReconciliation={count:recordedCount,expected:values.elapsed,total:recordedTotal,unexpected:unexpectedCount,complete:allExpectedReported,difference:fmsDiff};
 var alternative=null;
 if(values.altWage!==null||values.altHours!==null){
   var altWage=values.altWage===null?values.wage:values.altWage;
   var altHours=values.altHours===null?values.hours:values.altHours;
   var altMonthly=altWage*altHours*52/12*(1+values.burden/100)+values.other;
   var altProjected=values.spent+altMonthly*monthsLeft+values.onetime;
   alternative={monthly:altMonthly,projected:altProjected,difference:altProjected-projected,variance:values.budget-altProjected};
 }
 return {monthsLeft:monthsLeft,wages:baselineWages,employer:employer,monthly:monthly,future:future,projected:projected,variance:variance,remaining:values.budget-values.spent,average:values.budget/values.months,maxHours:maxHours,alternative:alternative,fmsReconciliation:fmsReconciliation};
}
function collect(){
 var v={budget:read("budget",true),months:read("months",true),elapsed:read("elapsed",true),spent:read("spent",true),wage:read("wage",true),hours:read("hours",true),burden:read("burden",true),other:read("other",true),onetime:read("onetime",true),altWage:read("altWage",false),altHours:read("altHours",false)};
 v.fmsMonths=Array.from({length:12},function(_,idx){return read("fms"+(idx+1),false);});
 if(v.elapsed>v.months)throw new Error("Elapsed months cannot exceed plan months.");
 // Allow actual FMS spending above the entered authorization so the app
 // displays an overspending warning instead of refusing to calculate.
 return v;
}
function report(v,r){
 current={v:v,r:r};
 el("error").textContent="";
 el("results").hidden=false;
 el("demoTag").hidden=!exampleActive;
 s("rBudget",money(v.budget));
 s("rRemaining",money(r.remaining));
 s("rProjected",money(r.projected));
 s("rVariance",money(r.variance));
 s("rMaxHours",r.maxHours===null?"Not estimated":r.maxHours.toLocaleString("en-US",{maximumFractionDigits:2})+" hrs/week");
 var rec=r.fmsReconciliation,recText="";
 if(rec.expected===0)recText="No completed plan months entered. Monthly FMS reconciliation is not needed yet.";
 else if(rec.unexpected>0)recText="Monthly report figures were entered for months after the elapsed plan period. Check the month positions; no reconciliation is confirmed.";
 else if(!rec.complete)recText="FMS report comparison incomplete: "+rec.count+" of "+rec.expected+" elapsed months entered. Blank months are treated as unknown, not as $0.";
 else if(Math.abs(rec.difference)<=0.01)recText="FMS monthly amounts match the entered spent-to-date total ("+money(rec.total)+") to the nearest cent. Confirm against the original FMS statement.";
 else recText="FMS reconciliation difference: monthly entries total "+money(rec.total)+", versus entered spent-to-date "+money(v.spent)+" (difference "+money(rec.difference)+"). Review the FMS reports before using this forecast.";
 el("fmsReconcile").textContent=recText;
 s("rVarianceLabel",r.variance<0?"Estimated amount over entered budget":"Estimated amount left after forecast");
 el("varianceTile").className="metric "+(r.variance<0?"red":"green");
 s("rMonths",String(r.monthsLeft));
 s("rAverage",money(r.average));
 s("rWages",money(r.wages));
 s("rEmployer",money(r.employer));
 s("rOther",money(v.other));
 s("rMonthly",money(r.monthly));
 s("rOneTime",money(v.onetime));
 s("rFuture",money(r.future));
 el("comparison").hidden=!r.alternative;
 if(r.alternative){
  s("rAltMonthly",money(r.alternative.monthly));
  s("rAltProjected",money(r.alternative.projected));
  s("rAltDifference",(r.alternative.difference>=0?"+":"")+money(r.alternative.difference));
  s("rAltVariance",money(r.alternative.variance));
 }
 var summary;
 if(r.monthsLeft===0&&v.onetime>0){summary="No months remain, but one-time future purchases are entered. Confirm timing and authorization with your FMS and consultation services provider.";}
 else if(r.variance<0){summary="This scenario projects spending above the amount you entered by "+money(-r.variance)+". Review the budget and options with your FMS and consultation services provider before committing funds.";}
 else {summary="Based on these assumptions, estimated spending would leave "+money(r.variance)+" unallocated. This is not confirmation that funds or purchases are available or approved.";}
 if(r.remaining<0)summary="FMS-reported spending already exceeds the entered authorization by "+money(-r.remaining)+". Review official FMS records and contact the consultation services provider immediately; this estimate cannot authorize additional spending.";
 else if(r.maxHours!==null&&v.hours>r.maxHours&&r.monthsLeft>0)summary+=" The illustrative weekly-hour upper bound at these entered costs is "+r.maxHours+" hours; this is NOT your authorized service-hours limit. Confirm any schedule change with your FMS and consultation services provider.";
 el("interpretation").textContent=summary;
 el("status").textContent="Calculated from the values entered in this browser. Nothing was submitted to AMICOR or DHS.";
}
form.addEventListener("submit",function(event){
 event.preventDefault();
 try{
  var v=collect(),r=calculate(v);report(v,r);
  // Bring the result into view on narrow screens and provide focus for
  // keyboard/screen-reader users after the explicit Calculate action.
  var target=el("resultTitle");
  if(target&&typeof target.focus==="function")target.focus({preventScroll:true});
  if(target&&typeof target.scrollIntoView==="function"){
   var reduced=typeof window.matchMedia==="function"&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
   target.scrollIntoView({behavior:reduced?"auto":"smooth",block:"start"});
  }
 }
 catch(error){el("error").textContent=error.message;el("results").hidden=true;current=null;}
});
form.addEventListener("input",function(){
 if(current){current=null;el("results").hidden=true;el("status").textContent="Values changed. Recalculate to update the outlook.";}
 el("error").textContent="";
 exampleActive=false;
});
el("example").addEventListener("click",function(){
 var sample={budget:48000,months:12,elapsed:3,spent:9500,wage:20,hours:30,burden:17,other:200,onetime:450,altWage:22,altHours:28,fms1:3200,fms2:3100,fms3:3200};
 // Clear any previous monthly report inputs so the fictional illustration
 // cannot accidentally reuse real/previous values from the form.
 for(var n=1;n<=12;n++)el("fms"+n).value="";
 Object.keys(sample).forEach(function(k){el(k).value=sample[k];});
 exampleActive=true;
 form.requestSubmit();
});
el("reset").addEventListener("click",function(){
 form.reset();Array.from({length:12},function(_,idx){el("fms"+(idx+1)).value="";});el("budget").value="";el("wage").value="";el("hours").value="";el("burden").value="";el("results").hidden=true;el("error").textContent="";el("status").textContent="Form reset. Enter an authorized budget and planned costs to begin.";current=null;exampleActive=false;
});
el("print").addEventListener("click",function(){if(current)window.print();});
function fileDownload(filename,contents,contentType){
 var blob=new Blob([contents],{type:contentType});
 var url=URL.createObjectURL(blob),link=document.createElement("a");
 link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();
 setTimeout(function(){URL.revokeObjectURL(url);},1000);
}
var fields=["budget","months","elapsed","spent","wage","hours","burden","other","onetime","altWage","altHours"];
el("savePlan").addEventListener("click",function(){
 if(!current)return;
 var data={kind:"amicor-cfss-plan",version:1,savedAt:new Date().toISOString(),fictionalExample:exampleActive,fields:{}};
 fields.forEach(function(id){data.fields[id]=current.v[id];});
 for(var j=1;j<=12;j++)data.fields["fms"+j]=current.v.fmsMonths[j-1];
 fileDownload("cfss-private-budget-plan.json",JSON.stringify(data,null,2),"application/json;charset=utf-8");
});
el("restoreBtn").addEventListener("click",function(){el("restoreFile").click();});
el("restoreFile").addEventListener("change",async function(){
 var f=this.files&&this.files[0];if(!f)return;
 try{
  if(f.size>50000)throw Error("Saved plan file is too large.");
  var data=JSON.parse(await f.text());
  if(!data||data.kind!=="amicor-cfss-plan"||data.version!==1||!data.fields||typeof data.fields!=="object")throw Error("This is not a supported CFSS plan file.");
  var parsed={},idlist=fields.concat(Array.from({length:12},function(_,i){return "fms"+(i+1);}));
  idlist.forEach(function(id){
   var val=data.fields[id],optional=id==="altWage"||id==="altHours"||id.slice(0,3)==="fms";
   if(val===null&&optional){parsed[id]="";return;}
   var input=el(id);
   if(typeof val!=="number"||!Number.isFinite(val)||val<Number(input.min||0)||(input.max&&val>Number(input.max))||(input.step==="1"&&!Number.isInteger(val)))throw Error("Saved file contains an invalid "+id+" amount.");
   parsed[id]=String(val);
  });
  if(Number(parsed.elapsed)>Number(parsed.months))throw Error("Elapsed months exceed the plan period.");
  // All values were validated above; restore them together only after the
  // entire file has passed validation, leaving previous inputs unchanged on errors.
  idlist.forEach(function(id){el(id).value=parsed[id];});
  exampleActive=data.fictionalExample===true;
  form.requestSubmit();
  if(current)el("status").textContent="Saved planning figures restored locally from your selected file; check them against your current FMS reports.";
 }catch(err){el("error").textContent="Could not restore plan: "+err.message;}
 finally{this.value="";}
});
el("download").addEventListener("click",function(){
 if(!current)return;
 var v=current.v,r=current.r;
 var lines=[["CFSS Budget Co-Pilot","Planning estimate - not an official DHS/FMS statement"],
 ["Fictional example",exampleActive?"Yes":"No"],
 ["Approved budget entered",money(v.budget)],["Plan months",v.months],["Months elapsed",v.elapsed],
 ["Reported spent to date",money(v.spent)],["Hourly wage entered",money(v.wage)],
 ["Weekly worker hours",v.hours],["Employer cost percentage entered",v.burden],
 ["Other monthly expenses",money(v.other)],["One-time planned purchases",money(v.onetime)],
 ["Months remaining",r.monthsLeft],["Average monthly authorized budget",money(r.average)],
 ["Monthly worker wages estimate",money(r.wages)],["Monthly employer cost estimate",money(r.employer)],
 ["Monthly total estimate",money(r.monthly)],["Future planned costs",money(r.future)],
 ["Projected total period spending",money(r.projected)],["Budget difference",money(r.variance)],["Illustrative weekly hours budget may cover",r.maxHours===null?"Not estimated":r.maxHours],["Weekly hours estimate status","Not authorization; verify with consultation and FMS provider"],["Monthly FMS report entries received",r.fmsReconciliation.count],["Monthly FMS report entries expected",r.fmsReconciliation.expected],["FMS monthly sum comparison",r.fmsReconciliation.complete?money(r.fmsReconciliation.difference):"Incomplete"]];
 if(r.alternative)lines.push(["Alternative hourly wage",v.altWage===null?money(v.wage):money(v.altWage)],["Alternative hours per week",v.altHours===null?v.hours:v.altHours],["Alternative monthly estimate",money(r.alternative.monthly)],["Alternative projected period spending",money(r.alternative.projected)],["Alternative budget difference",money(r.alternative.variance)]);
 lines.push(["Notice","Planning estimates only; confirm spending and allowable expenses with your FMS provider."]);
 v.fmsMonths.forEach(function(amount,idx){if(amount!==null)lines.push(["FMS reported month "+(idx+1),money(amount)]);});
 var csv=lines.map(function(row){return row.map(function(item){return '"'+String(item).replace(/"/g,'""')+'"';}).join(",");}).join("\r\n");
 var blob=new Blob([csv],{type:"text/csv;charset=utf-8"});var url=URL.createObjectURL(blob);var link=document.createElement("a");link.href=url;link.download="cfss-budget-planning-scenario.csv";document.body.appendChild(link);link.click();link.remove();setTimeout(function(){URL.revokeObjectURL(url);},1000);
});
})();
