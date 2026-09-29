(function(){
  "use strict";
  var form=document.getElementById("agent-intake");
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