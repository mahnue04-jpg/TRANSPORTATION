(function(){
  "use strict";
  const status=document.getElementById("status"), results=document.getElementById("results"),
    list=document.getElementById("list"), count=document.getElementById("count"),btn=document.getElementById("load");
  function el(name,cls,value){const node=document.createElement(name);if(cls)node.className=cls;if(value!==undefined)node.textContent=String(value);return node;}
  function state(message,style){status.textContent=message;status.className="state "+(style||"");}
  async function load(){
    btn.disabled=true;results.hidden=true;list.replaceChildren();state("Checking owner access…","");
    try{
      const response=await fetch("/nova-growth/owner/api",{credentials:"same-origin",cache:"no-store",headers:{"Accept":"application/json"}});
      const type=response.headers.get("content-type")||"";
      if(!type.includes("application/json")){state("Owner authentication is required. Confirm Cloudflare Access is configured for this private route.","error");return;}
      const data=await response.json();
      if(!response.ok||!data.ok){
        state(response.status===503?"Private inbox is not configured or unavailable. No customer data was returned.":"Owner access denied. No customer data was returned.","error");
        return;
      }
      if(!Array.isArray(data.rows)){state("Unexpected response. Inbox remains unavailable.","error");return;}
      state("Owner-verified inbox connected.","ok");results.hidden=false;
      count.textContent=data.rows.length+" recent consented inquiries"+(data.complete?"":" (partial listing; more entries may exist)");
      for(const item of data.rows){
        const article=el("article","item");
        article.appendChild(el("h3","",item.name||"Unnamed contact"));
        article.appendChild(el("p","meta",[item.company,item.product,item.receivedAt].filter(Boolean).join(" · ")));
        article.appendChild(el("p","meta",[item.email,item.phone].filter(Boolean).join(" · ")));
        article.appendChild(el("p","message",item.message||""));
        article.appendChild(el("p","meta","Status: needs owner review. No automatic messages were sent."));
        list.appendChild(article);
      }
      if(!data.rows.length)list.appendChild(el("p","muted","No consented inquiries were returned."));
    }catch{state("Unable to reach the private inbox. No customer data was returned.","error");}
    finally{btn.disabled=false;}
  }
  btn.addEventListener("click",load);
})();

