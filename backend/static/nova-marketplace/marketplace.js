const esc=(value)=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function loadCatalog(){
  const root=document.getElementById("catalog");
  const legacy=document.getElementById("legacy-summary");
  try{
    const res=await fetch("/static/nova-marketplace/catalog.json",{cache:"no-store"});
    if(!res.ok) throw new Error("Catalog unavailable");
    const data=await res.json();
    root.innerHTML=data.products.map(p=>`
      <article>
        <img class="thumb" src="${esc(p.thumbnail_url)}" alt="" loading="lazy">
        <span class="status">MIGRATED · REVIEW</span>
        <h2>${esc(p.name)}</h2>
        <p>${esc(p.short_description)}</p>
        <div class="meta">$${Number(p.price_usd).toFixed(2)} · ${esc(p.pricing_type)}</div>
        <a class="details" href="/nova/marketplace/product/${encodeURIComponent(p.slug)}">View migrated details</a>
        <button disabled>Checkout pending verification</button>
      </article>`).join("");
    legacy.textContent=`${data.legacy_review.length} older Webflow commerce records are preserved for reconciliation and are not published as purchasable products.`;
  }catch(err){
    root.innerHTML="<p>Marketplace catalog could not be loaded.</p>";
    legacy.textContent="Legacy reconciliation data unavailable.";
  }
}
loadCatalog();