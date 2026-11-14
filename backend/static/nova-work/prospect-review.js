(function () {
  "use strict";
  const panel = document.getElementById("prospect-review-panel");
  if (!panel) return;
  const form = document.getElementById("prospect-review-form");
  const discoveryForm = document.getElementById("prospect-discovery-form");
  const status = document.getElementById("prospect-review-status");
  const results = document.getElementById("prospect-review-records");
  const savedReviews = document.getElementById("prospect-review-saved");
  const refresh = document.getElementById("prospect-review-refresh");
  const resume = document.getElementById("prospect-review-resume");
  const download = document.getElementById("prospect-review-download");
  const workPackage = document.getElementById("prospect-review-package");
  const sources = document.getElementById("prospect-review-sources");
  let job = "", busy = false, requestKey = "", signature = "";
  let sessionEpoch = 0;
  function headers() {
    return window.AmiCorSession && window.AmiCorSession.getAuthHeaders
      ? window.AmiCorSession.getAuthHeaders() || {} : {};
  }
  async function request(path, options) {
    const auth = headers();
    if (!(auth.Authorization || auth.authorization)) throw new Error("Sign in as the owner first.");
    const response = await fetch("/api/nova/work/prospect-review/" + path,
      Object.assign({}, options, {credentials:"same-origin", headers:Object.assign({},auth,options && options.headers)}));
    if (!response.ok) {
      let message = "Research request failed (" + response.status + ").";
      try {const body=await response.json();if(typeof body.detail === "string")message=body.detail;}catch (_) {}
      throw new Error(message);
    }
    return response;
  }
  function show(data) {
    job=data.job_id;download.disabled=false;workPackage.disabled=false;results.replaceChildren();
    const rows=Array.isArray(data.records)?data.records:[];
    status.textContent=rows.length+" source records saved; "+data.summary.workflow_candidates+
      " preliminary workflow matches; "+data.summary.insufficient_evidence+" need stronger evidence; "+data.source_failures.length+
      " source failures. Review pending. Buying interest unverified. Outreach remains on hold.";
    rows.forEach(function(row){
      const item=document.createElement("article");
      const title=document.createElement("h3");title.textContent=row.business;
      const source=document.createElement("p");source.textContent="Source: "+row.source_url+". Checked: "+row.checked_at;
      const evidence=document.createElement("p");evidence.textContent=row.evidence.map(e=>e.excerpt).join("; ");
      const next=document.createElement("p");next.textContent=row.status==="INSUFFICIENT_EVIDENCE"?"Hold: obtain stronger primary evidence before campaign planning.":row.next_action;
      item.append(title,source,evidence,next);results.appendChild(item);
    });
    try{sessionStorage.setItem("nova-prospect-review-job",job);}catch (_){}
  }
  function lock(value){busy=value;refresh.disabled=value;savedReviews.disabled=value;form.querySelector('button[type="submit"]').disabled=value;discoveryForm.querySelector('button[type="submit"]').disabled=value;resume.disabled=value;download.disabled=value||!job;workPackage.disabled=value||!job;}
  async function available(){
    sessionEpoch += 1;
    const epoch = sessionEpoch;
    panel.hidden=true;results.replaceChildren();savedReviews.replaceChildren();savedReviews.value="";job="";download.disabled=true;workPackage.disabled=true;
    try {const r=await request("readiness");const data=await r.json();if(epoch===sessionEpoch)panel.hidden=!data.enabled;} catch (_) {}
  }
  form.addEventListener("submit",async function(event){
    event.preventDefault();if(busy)return;
    const rows=sources.value.split(/\r?\n/).filter(s=>s.trim()).map(function(line){
      const split=line.indexOf("|");return split<1?{name:"",url:""}:{name:line.slice(0,split).trim(),url:line.slice(split+1).trim()};
    });
    if(!rows.length||rows.length>25||rows.some(r=>!r.name||!r.url.startsWith("https://"))){status.textContent="Enter 1–25 lines as Business name | https://official-source-page";return;}
    const current=JSON.stringify(rows);
    if(signature!==current){
      if(!window.crypto || !window.crypto.randomUUID){status.textContent="Secure request IDs are unavailable in this browser.";return;}
      signature=current;requestKey=window.crypto.randomUUID();
    }
    const epoch = sessionEpoch;
    lock(true);status.textContent="Reviewing public sources and preparing the Operations review copy...";
    try {
      const r=await request("jobs",{method:"POST",headers:{"Content-Type":"application/json","X-Nova-Owner-Action":"review-public-prospect-sources"},body:JSON.stringify({request_key:requestKey,sources:rows})});
      const data=await r.json();if(epoch===sessionEpoch)show(data);
    }catch(error){status.textContent=error.message;}finally{lock(false);}
  });
  discoveryForm.addEventListener("submit",async function(event){
    event.preventDefault();if(busy)return;
    const query=document.getElementById("prospect-discovery-query").value.trim();
    if(query.length<10||query.length>300){status.textContent="Enter a specific public business research query.";return;}
    const current="discovery:"+query;
    if(signature!==current){
      if(!window.crypto||!window.crypto.randomUUID){status.textContent="Secure request IDs are unavailable.";return;}
      signature=current;requestKey=window.crypto.randomUUID();
    }
    const epoch=sessionEpoch;lock(true);status.textContent="Searching for business candidates, then checking their public pages...";
    try{
      const r=await request("discover",{method:"POST",headers:{"Content-Type":"application/json","X-Nova-Owner-Action":"discover-public-business-candidates"},body:JSON.stringify({request_key:requestKey,query:query,limit:5})});
      const data=await r.json();if(epoch===sessionEpoch)show(data);
    }catch(error){status.textContent=error.message;}finally{lock(false);}
  });
  resume.addEventListener("click",async function(){
    if(busy)return;
    const epoch=sessionEpoch;
    job=savedReviews.value||"";
    if(!job){try {job=sessionStorage.getItem("nova-prospect-review-job")||"";}catch (_){}}
    if(!job){status.textContent="Choose Find my saved reviews, then select an assignment to resume.";return;}
    lock(true);
    try{const r=await request("jobs/"+encodeURIComponent(job));const data=await r.json();if(epoch===sessionEpoch)show(data);}
    catch(error){results.replaceChildren();job="";status.textContent=error.message;}finally{lock(false);}
  });
  download.addEventListener("click",async function(){
    if(!job||busy)return;lock(true);
    const epoch=sessionEpoch;
    try{
      const r=await request("jobs/"+encodeURIComponent(job)+"/review.csv");
      const blob=await r.blob();if(epoch!==sessionEpoch)return;
      const url=URL.createObjectURL(blob);const link=document.createElement("a");
      link.href=url;link.download="nova-prospect-review.csv";document.body.appendChild(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(url),10000);
    }catch(error){status.textContent=error.message;}finally{lock(false);}
  });
  refresh.addEventListener("click",async function(){
    if(busy)return;const epoch=sessionEpoch;lock(true);
    try{
      const r=await request("jobs");const data=await r.json();if(epoch!==sessionEpoch)return;
      savedReviews.replaceChildren();savedReviews.value="";
      const placeholder=document.createElement("option");placeholder.value="";placeholder.textContent="Choose a saved review";savedReviews.appendChild(placeholder);
      data.jobs.forEach(function(item){const option=document.createElement("option");option.value=item.job_id;option.textContent=item.businesses.join(", ")+" ("+item.record_count+" records; "+item.job_id.slice(0,8)+")";savedReviews.appendChild(option);});
      status.textContent=data.jobs.length+" saved reviews found. Select one and choose Resume. "+data.unavailable_count+" unavailable or incomplete reviews excluded.";
    }catch(error){if(epoch===sessionEpoch)status.textContent=error.message;}finally{lock(false);}
  });
  workPackage.addEventListener("click",async function(){
    if(!job||busy)return;lock(true);const epoch=sessionEpoch;
    try{
      const r=await request("jobs/"+encodeURIComponent(job)+"/work-package.zip");
      const blob=await r.blob();if(epoch!==sessionEpoch)return;
      const url=URL.createObjectURL(blob);const link=document.createElement("a");
      link.href=url;link.download="nova-supervised-work-package.zip";document.body.appendChild(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(url),10000);
    }catch(error){status.textContent=error.message;}finally{lock(false);}
  });
  window.addEventListener("amicor:session-recovered",available);
  window.addEventListener("amicor:session-invalid",function(){sessionEpoch+=1;panel.hidden=true;results.replaceChildren();savedReviews.replaceChildren();savedReviews.value="";job="";});
  available();
})();
