const esc=(v)=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function api(path, options){
  const opts = {...(options||{})};
  let r;
  if (window.AmiCorSession && typeof window.AmiCorSession.ensureReady === "function") {
    await window.AmiCorSession.ensureReady();
  }
  if (window.AmiCorSession && typeof window.AmiCorSession.authFetch === "function") {
    r = await window.AmiCorSession.authFetch(path, opts);
  } else {
    const headers = {...(opts.headers||{})};
    try {
      const ident = JSON.parse(localStorage.getItem("amicor_identity") || "{}");
      const token = ident.accessToken || ident.access_token;
      if (token) headers.Authorization = "Bearer " + token;
    } catch (_) {}
    r = await fetch(path,{credentials:"include",...opts,headers});
  }
  let body={};
  try{body=await r.json()}catch(_){}
  if(!r.ok)throw new Error(body.detail||("Request failed: "+r.status));
  return body;
}

async function ensureMarketplaceAdminRole(){
  if (!window.AmiCorSession) return;
  const profile = typeof window.AmiCorSession.getSessionProfile === "function"
    ? window.AmiCorSession.getSessionProfile()
    : null;
  const role = String(profile && profile.role || "").toLowerCase();
  if (role === "admin" || role === "super_admin_support") return;

  const authorized = Array.isArray(profile && profile.authorizedRoles)
    ? profile.authorizedRoles.map(v => String(v || "").toLowerCase())
    : [];
  if (authorized.includes("admin") && typeof window.AmiCorSession.switchWorkspaceRole === "function") {
    await window.AmiCorSession.switchWorkspaceRole("admin");
  }
}

async function load(){
 const root=document.getElementById("admin-products");
 try{
   const s=await api("/api/nova/marketplace/status");
   root.innerHTML=(s.products||[]).map(p=>`
    <article data-slug="${esc(p.slug)}">
      <span class="status">${p.verified?"VERIFIED":"NOT READY"}</span>
      <h2>${esc(p.filename)}</h2>
      <p>${p.verified?"Approved file is installed and verified.":"Upload the exact approved PDF for this product."}</p>
      <div class="meta">${p.access==="free"?"FREE":"PAID"} · $${(Number(p.price_cents||0)/100).toFixed(2)}</div>
      <form class="upload-form">
        <input type="file" accept="application/pdf,.pdf" required>
        <button type="submit">${p.verified?"Replace / re-verify":"Upload approved PDF"}</button>
        <p class="upload-message"></p>
      </form>
    </article>`).join("");
   document.querySelectorAll(".upload-form").forEach(form=>{
     form.addEventListener("submit",async e=>{
       e.preventDefault();
       const card=form.closest("article"),slug=card.dataset.slug,msg=form.querySelector(".upload-message"),btn=form.querySelector("button"),file=form.querySelector("input").files[0];
       if(!file)return;
       btn.disabled=true;msg.textContent="Checking admin session…";
       const fd=new FormData();fd.append("file",file);
       try{
         await ensureMarketplaceAdminRole();
         msg.textContent="Uploading and verifying…";
         await api("/api/nova/marketplace/admin/products/"+encodeURIComponent(slug)+"/file",{method:"POST",body:fd});
         msg.textContent="Verified successfully.";
         await load();
       }catch(err){msg.textContent=err.message;btn.disabled=false;}
     });
   });
 }catch(err){root.innerHTML="<p>"+esc(err.message)+"</p>";}
}
load();