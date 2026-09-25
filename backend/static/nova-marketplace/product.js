const esc=(v)=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money=(p)=>Number(p.price_usd)===0?"FREE":"$"+Number(p.price_usd).toFixed(2);
(async()=>{
  const root=document.getElementById("product");
  const slug=decodeURIComponent(location.pathname.split("/").filter(Boolean).pop()||"");
  try{
    const [cr,sr]=await Promise.all([
      fetch("/static/nova-marketplace/catalog.json",{cache:"no-store"}),
      fetch("/api/nova/marketplace/status",{cache:"no-store"})
    ]);
    const d=await cr.json();
    const status=sr.ok?await sr.json():{products:[]};
    const p=d.products.find(x=>x.slug===slug);
    if(!p){root.innerHTML="<h1>Product not found</h1>";return;}
    const fs=(status.products||[]).find(x=>x.slug===slug)||{};
    const free=p.pricing_type==="Free"||Number(p.price_usd)===0;
    document.title=p.name+" · AMICOR";
    let action="";
    if(!fs.verified){
      action='<div class="notice"><strong>Product file setup in progress.</strong> AMICOR will not accept payment or provide a download until the approved file is verified in private storage.</div><button disabled>Not ready yet</button>';
    }else if(free){
      action=`<div class="notice"><strong>Free product.</strong> The approved PDF is verified and ready.</div><a class="details" href="/api/nova/marketplace/products/${encodeURIComponent(slug)}/download">Download free PDF</a>`;
    }else{
      action=`<div class="notice"><strong>Stripe TEST checkout only.</strong> No live charge is enabled. Enter an email only when performing the controlled test.</div><form id="checkout-form"><label>Email for TEST purchase <input id="checkout-email" type="email" required autocomplete="email"></label><button type="submit">Start TEST checkout · ${money(p)}</button><p id="checkout-message"></p></form>`;
    }
    root.innerHTML=`<p class="eyebrow">${free?"FREE RESOURCE":"AMICOR DIGITAL PRODUCT"}</p><h1>${esc(p.name)}</h1><img class="thumb" src="${esc(p.hero_url)}" alt="" style="height:auto;max-height:420px"><p>${esc(p.short_description)}</p><div class="meta">${money(p)} · ${esc(p.pricing_type)}</div><h2>What this product includes</h2><ul>${p.benefits.map(b=>`<li>${esc(b)}</li>`).join("")}</ul>${action}`;
    const form=document.getElementById("checkout-form");
    if(form){
      form.addEventListener("submit",async(e)=>{
        e.preventDefault();
        const msg=document.getElementById("checkout-message");
        const button=form.querySelector("button");
        button.disabled=true; msg.textContent="Opening Stripe TEST checkout…";
        try{
          const response=await fetch("/api/nova/marketplace/checkout",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({product_slug:slug,email:document.getElementById("checkout-email").value})});
          const body=await response.json();
          if(!response.ok) throw new Error(body.detail||"TEST checkout unavailable");
          if(!body.checkout_url) throw new Error("Stripe TEST checkout URL missing");
          location.assign(body.checkout_url);
        }catch(err){msg.textContent=err.message;button.disabled=false;}
      });
    }
  }catch(e){root.innerHTML="<h1>Product could not be loaded</h1>";}
})();
