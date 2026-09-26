(function(){
  "use strict";
  var form=document.getElementById("agent-intake");
  var status=document.getElementById("status");
  function setStatus(message,ok){status.textContent=message;status.className="status "+(ok?"ok":"err");}
  form.addEventListener("submit",async function(event){
    event.preventDefault();
    setStatus("Submitting your work request…",true);
    var payload={
      lead_type:"anonymous_operations",
      organization_name:document.getElementById("organization").value.trim()||null,
      contact_name:document.getElementById("name").value.trim(),
      work_email:document.getElementById("email").value.trim(),
      phone:document.getElementById("phone").value.trim()||null,
      preferred_contact_method:document.getElementById("contact-method").value,
      subject:"Nova Anonymous Operations work request",
      message:"Selected plan: "+document.getElementById("service-plan").value+"\n\n"+document.getElementById("message").value.trim(),
      consent:document.getElementById("consent").checked,
      source_path:"/nova/anonymous-agent",
      lead_source:"nova_anonymous_operations",
      website:document.getElementById("website").value
    };
    try{
      var response=await fetch("/api/marketing/leads",{method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},body:JSON.stringify(payload)});
      var body={}; try{body=await response.json();}catch(_){}
      if(!response.ok) throw new Error((body&&body.detail)||"Unable to submit the request.");
      form.reset();
      setStatus("Request received. AMICOR will review the task and contact you using your selected contact method.",true);
    }catch(err){setStatus(err.message||"Unable to submit the request.",false);}
  });
}());