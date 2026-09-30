(function(){
  "use strict";
  var form=document.getElementById("agent-intake");
  function refreshAccountState(){
    var manager=window.AmiCorSession||null;
    if(manager&&manager.restore) manager.restore();
    var current=manager&&manager.getCurrent?manager.getCurrent():null;
    var ident=current&&current.identity?current.identity:null;
    var signedIn=!!(ident&&manager&&manager.getAccessToken&&manager.getAccessToken());
    var out=document.getElementById("agent-account-signed-out");
    var inside=document.getElementById("agent-account-signed-in");
    if(out) out.classList.toggle("hidden",signedIn);
    if(inside) inside.classList.toggle("hidden",!signedIn);
    if(signedIn){
      var name=document.getElementById("agent-account-name");
      if(name) name.textContent="Signed in as "+(ident.name||ident.email||"AMICOR Nova customer");
    }
  }
  refreshAccountState();
  var signOut=document.getElementById("agent-sign-out");
  if(signOut){
    signOut.addEventListener("click",async function(){
      var manager=window.AmiCorSession||null;
      if(manager&&manager.logout) await manager.logout();
      window.location.href="/nova/anonymous-agent";
    });
  }

  function demoText(id,value){
    var node=document.getElementById(id);
    if(node) node.textContent=value;
  }
  function compact(value,max){
    var clean=String(value||"").replace(/\s+/g," ").trim();
    if(clean.length<=max) return clean;
    return clean.slice(0,max-1).trim()+"…";
  }
  function classifyDemo(request){
    var text=String(request||"").toLowerCase();
    var category="Operations support";
    if(/lead|estimate|prospect|follow.?up|crm/.test(text)) category="Lead & follow-up operations";
    else if(/invoice|billing|payment|expense|bookkeep/.test(text)) category="Administrative finance support";
    else if(/customer|inquir|support|message|email|inbox/.test(text)) category="Customer-support operations";
    else if(/report|document|proposal|rfp/.test(text)) category="Document & reporting operations";

    var urgent=/urgent|asap|immediate|today|complaint|angry|emergency/.test(text);
    var decision=/price|pricing|quote|contract|refund|legal|approve|approval|discount|commit/.test(text);
    var priority=urgent?"High":(/follow.?up|customer|lead|estimate|deadline/.test(text)?"Medium":"Normal");
    var escalation=[];
    if(urgent) escalation.push("urgent item");
    if(decision) escalation.push("owner decision");
    if(!escalation.length) escalation.push("exceptions or decisions outside the approved workflow");
    return {category:category,priority:priority,escalation:escalation.join(" and ")};
  }
  function runOperationsDemo(){
    var name=(document.getElementById("demo-name").value||"New lead").trim();
    var business=(document.getElementById("demo-business").value||"Client business").trim();
    var request=(document.getElementById("demo-request").value||"").trim();
    if(!request){
      document.getElementById("demo-request").focus();
      return;
    }
    var result=classifyDemo(request);
    demoText("demo-intake",compact(name,80)+" · "+compact(business,100)+" · request captured with source, timestamp, and required-field check.");
    demoText("demo-classification",result.category+" · Priority: "+result.priority+" · Summary: "+compact(request,220));
    demoText("demo-record","Status: New → Reviewed. Owner: Operations queue. Next action: prepare follow-up and track response. No external system is changed in this sandbox.");
    demoText("demo-followup","Draft: “Hi "+compact(name,60)+", thanks for reaching out. We received your request and are organizing the next steps. We’ll confirm any item that requires an owner decision before action is taken.”");
    demoText("demo-escalation","Nova would route "+result.escalation+" to the authorized owner instead of deciding or acting on it automatically.");
    demoText("demo-report","Adds 1 new item, 1 reviewed item, 1 follow-up prepared, and "+(result.priority==="High"?"1 priority escalation":"0 priority escalations")+" to the daily operations summary.");
    var output=document.getElementById("demo-output");
    if(output) output.classList.remove("hidden");
  }
  var runDemo=document.getElementById("run-operations-demo");
  if(runDemo) runDemo.addEventListener("click",runOperationsDemo);
  var resetDemo=document.getElementById("reset-operations-demo");
  if(resetDemo) resetDemo.addEventListener("click",function(){
    document.getElementById("demo-name").value="Jordan Lee";
    document.getElementById("demo-business").value="Northstar Home Services";
    document.getElementById("demo-request").value="We need help organizing customer inquiries, following up on estimates that have not received responses, and making sure urgent requests get to the owner.";
    var output=document.getElementById("demo-output");
    if(output) output.classList.add("hidden");
  });

  var status=document.getElementById("status");
  var paidPlans={starter_49:true,launch_99:true,business_299:true};
  function setStatus(message,ok){status.textContent=message;status.className="status "+(ok?"ok":"err");}
  function responseData(body){return body&&body.data?body.data:body||{};}
  function checkoutNotice(){
    var params=new URLSearchParams(window.location.search||"");
    var result=params.get("checkout");
    if(result==="success") setStatus("Secure checkout returned successfully. Stripe confirmation is being recorded; AMICOR will review the requested scope before execution.",true);
    if(result==="cancelled") setStatus("Checkout was cancelled. Your saved work request remains available; no new checkout was confirmed.",false);
  }
  checkoutNotice();
  form.addEventListener("submit",async function(event){
    event.preventDefault();
    var plan=document.getElementById("service-plan").value;
    if(paidPlans[plan]&&!document.getElementById("terms-accepted").checked){
      setStatus("Accept the AMICOR terms before starting a paid checkout.",false);
      return;
    }
    setStatus("Submitting your work request…",true);
    var payload={
      lead_type:"anonymous_operations",
      organization_name:document.getElementById("organization").value.trim()||null,
      contact_name:document.getElementById("name").value.trim(),
      work_email:document.getElementById("email").value.trim(),
      phone:document.getElementById("phone").value.trim()||null,
      preferred_contact_method:document.getElementById("contact-method").value,
      subject:"Nova Anonymous Operations Agent work request",
      service_plan:plan,
      message:document.getElementById("message").value.trim(),
      consent:document.getElementById("consent").checked,
      source_path:"/nova/anonymous-agent",
      lead_source:"nova_anonymous_operations",
      website:document.getElementById("website").value
    };
    try{
      var response=await fetch("/api/marketing/leads",{method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},body:JSON.stringify(payload)});
      var body={}; try{body=await response.json();}catch(_){}
      if(!response.ok) throw new Error((body&&body.detail)||"Unable to submit the request.");
      var saved=responseData(body);
      if(paidPlans[plan]&&saved.lead_id){
        setStatus("Request saved. Opening secure Stripe Checkout…",true);
        var checkout=await fetch("/api/marketing/leads/"+encodeURIComponent(saved.lead_id)+"/checkout",{
          method:"POST",
          headers:{"Content-Type":"application/json","Accept":"application/json"}
        });
        var checkoutBody={}; try{checkoutBody=await checkout.json();}catch(_){}
        if(!checkout.ok) throw new Error((checkoutBody&&checkoutBody.detail)||"Secure checkout is not available yet.");
        if(checkoutBody.checkout_url){
          window.location.href=checkoutBody.checkout_url;
          return;
        }
        throw new Error("Secure checkout did not return a payment page.");
      }
      form.reset();
      if(plan==="free_scope"){
        setStatus("Free Scope Check received. AMICOR will review the task and contact you using your selected contact method.",true);
      }else{
        setStatus("Request received. AMICOR will review the task and contact you using your selected contact method.",true);
      }
    }catch(err){setStatus(err.message||"Unable to submit the request.",false);}
  });
}());