const esc=(value)=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money=(p)=>Number(p.price_usd)===0?"FREE":"$"+Number(p.price_usd).toFixed(2);
async function loadCatalog(){
  const root=document.getElementById("catalog");
  const legacy=document.getElementById("legacy-summary");
  try{
    const [catalogRes,statusRes]=await Promise.all([
      fetch("/static/nova-marketplace/catalog.json",{cache:"no-store"}),
      fetch("/api/nova/marketplace/status",{cache:"no-store"})
    ]);
    if(!catalogRes.ok) throw new Error("Catalog unavailable");
    const data=await catalogRes.json();
    const status=statusRes.ok?await statusRes.json():{products:[]};
    const ready=new Map((status.products||[]).map(x=>[x.slug,x]));
    root.innerHTML=data.products.map(p=>{
      const s=ready.get(p.slug)||{};
      const free=p.pricing_type==="Free"||Number(p.price_usd)===0;
      const fileReady=Boolean(s.verified);
      const badge=fileReady?(free?"FREE · READY":"FILE VERIFIED · TEST CHECKOUT"):"DELIVERABLE SETUP";
      return `
      <article>
        <img class="thumb" src="${esc(p.thumbnail_url)}" alt="" loading="lazy">
        <span class="status">${badge}</span>
        <h2>${esc(p.name)}</h2>
        <p>${esc(p.short_description)}</p>
        <div class="meta">${money(p)} · ${esc(p.pricing_type)}</div>
        <a class="details" href="/nova/marketplace/product/${encodeURIComponent(p.slug)}">View product</a>
      </article>`;
    }).join("");
    if(data.bundle){
      root.insertAdjacentHTML("beforeend",`<article><span class="status">BUNDLE · COMING AFTER TEST</span><h2>${esc(data.bundle.name)}</h2><p>All four paid AMICOR AI guides plus the free Side Income Checklist.</p><div class="meta">$${Number(data.bundle.price_usd).toFixed(2)} · One-Time</div></article>`);
    }
    legacy.textContent=`${data.legacy_review.length} older Webflow commerce records remain quarantined for reconciliation and are not purchasable.`;
  }catch(err){
    root.innerHTML="<p>Marketplace catalog could not be loaded.</p>";
    legacy.textContent="Legacy reconciliation data unavailable.";
  }
}
loadCatalog();
