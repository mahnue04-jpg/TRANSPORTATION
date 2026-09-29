"use strict";
(function () {
  var banner=document.getElementById("banner"),form=document.getElementById("signup-form");
  var offerSlots=document.getElementById("offer-slots"),paymentMode=document.getElementById("payment-mode"),submitBtn=document.getElementById("submit-btn");
  function show(message,ok){banner.textContent=message;banner.classList.remove("hidden");banner.classList.toggle("ok",!!ok);}
  function field(id){return (document.getElementById(id).value||"").trim();}
  fetch("/api/nova/signup/offer").then(function(r){return r.json();}).then(function(offer){
    offerSlots.textContent=offer.founding_available?(offer.founding_slots_remaining+" founding paid-plan slots remaining of "+offer.founding_cap+"."):"Founding paid-plan slots are filled; standard paid pricing remains available after the trial.";
    var mode=String(offer.payment_mode||"not_configured");
    if(mode==="live") paymentMode.textContent="Paid upgrades: LIVE secure Stripe Checkout is ready.";
    else if(mode==="test") paymentMode.textContent="Paid upgrades: Stripe TEST mode is ready; no live charge.";
    else if(mode==="live_gated") paymentMode.textContent="Paid upgrades: live Stripe is detected but activation remains gated.";
    else paymentMode.textContent="The free trial does not require Stripe or a payment card.";
  }).catch(function(){offerSlots.textContent="Paid-plan details will be confirmed when you choose to upgrade.";paymentMode.textContent="The free trial does not require a payment card.";});
  form.addEventListener("submit",function(event){
    event.preventDefault();submitBtn.disabled=true;
    fetch("/api/nova/signup/free",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
      business_name:field("business_name"),contact_name:field("contact_name"),email:field("email"),phone:field("phone"),industry:field("industry"),
      password:document.getElementById("password").value,terms_accepted:document.getElementById("terms_accepted").checked
    })}).then(function(r){return r.json().then(function(body){return{ok:r.ok,body:body};});}).then(function(result){
      if(!result.ok){
        var detail=(result.body&&result.body.detail)||"Signup failed.";
        if(String(detail).toLowerCase().indexOf("already registered")>=0){
          banner.innerHTML='This email already has an AMICOR Nova account. <a href="/nova?signin=1">Sign in to your existing account</a>.';
          banner.classList.remove("hidden");banner.classList.remove("ok");
        }else{show(detail);}
        submitBtn.disabled=false;return;
      }
      if(result.body.login_ready){
        show("Your 7-day AMICOR Nova trial is active. Sign in to use Ask Nova and the Operations Agent.",true);
        window.setTimeout(function(){window.location.href="/nova";},1200);return;
      }
      show("Account created, but trial activation is not available yet.");submitBtn.disabled=false;
    }).catch(function(){show("Network error. Account was not confirmed.");submitBtn.disabled=false;});
  });
})();