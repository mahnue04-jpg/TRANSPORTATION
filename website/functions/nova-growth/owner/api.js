// Owner-only Cloudflare KV inbox. Fail closed unless Cloudflare Access is configured.
// Required Cloudflare Pages environment variables:
// GROWTH_ACCESS_DOMAIN=https://<team>.cloudflareaccess.com
// GROWTH_ACCESS_AUD=<Access application audience>
 // GROWTH_OWNER_EMAIL=<owner identity email>
// Require a Cloudflare Access self-hosted application covering /nova-growth/owner/*.
// This endpoint does not update leads, send messages, or depend on Render.
const send=(status,data)=>new Response(JSON.stringify(data),{status,headers:{
  "content-type":"application/json; charset=utf-8",
  "cache-control":"private, no-store, max-age=0",
  "x-content-type-options":"nosniff",
  "referrer-policy":"no-referrer",
  "content-security-policy":"default-src 'none'"
}});
const decode=(part)=>{const s=part.replace(/-/g,"+").replace(/_/g,"/");const raw=atob(s+"=".repeat((4-s.length%4)%4));return Uint8Array.from(raw,c=>c.charCodeAt(0));};
const parse=(part)=>JSON.parse(new TextDecoder().decode(decode(part)));
async function authorize(request,env){
  const domain=String(env.GROWTH_ACCESS_DOMAIN||"").replace(/\/$/,"");
  const aud=String(env.GROWTH_ACCESS_AUD||"").trim();
  const owner=String(env.GROWTH_OWNER_EMAIL||"").toLowerCase().trim();
  if(!/^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com$/.test(domain)||!aud||!owner) return {status:503};
  const jwt=request.headers.get("Cf-Access-Jwt-Assertion")||"";
  const parts=jwt.split(".");
  if(parts.length!==3||parts.some(p=>!p||p.length>12000))return {status:403,reason:"missing_or_invalid_access_assertion"};
  try{
    const header=parse(parts[0]),body=parse(parts[1]);
    if(header.alg!=="RS256"||typeof header.kid!=="string"||header.kid.length>256)return {status:403,reason:"unsupported_access_token_header"};
    const now=Math.floor(Date.now()/1000);
    if(body.iss!==domain)return {status:403,reason:"access_domain_mismatch"};
    if(!Array.isArray(body.aud)||!body.aud.includes(aud))return {status:403,reason:"application_audience_mismatch"};
    if(typeof body.exp!=="number"||body.exp<=now||
       (body.nbf!==undefined&&(typeof body.nbf!=="number"||body.nbf>now))||
       (body.iat!==undefined&&(typeof body.iat!=="number"||body.iat>now+60)))return {status:403,reason:"access_token_time_invalid"};
    if(String(body.email||"").toLowerCase()!==owner)return {status:403,reason:"owner_identity_mismatch"};
    const response=await fetch(domain+"/cdn-cgi/access/certs",{redirect:"error"});
    if(!response.ok)return {status:503};
    const certs=await response.json();
    const jwk=(Array.isArray(certs.keys)?certs.keys:[]).find(k=>k.kid===header.kid&&k.kty==="RSA");
    if(!jwk)return {status:403,reason:"access_signing_key_not_found"};
    const key=await crypto.subtle.importKey("jwk",jwk,{name:"RSASSA-PKCS1-v1_5",hash:"SHA-256"},false,["verify"]);
    const sig=decode(parts[2]);
    const message=new TextEncoder().encode(parts[0]+"."+parts[1]);
    const valid=await crypto.subtle.verify("RSASSA-PKCS1-v1_5",key,sig,message);
    return {status:valid?200:403,...(valid?{}:{reason:"access_signature_invalid"})};
  }catch{return {status:403,reason:"access_token_validation_failed"};}
}
export async function onRequest(context){
  const {request,env}=context;
  if(request.method!=="GET")return send(405,{ok:false,error:"method_not_allowed"});
  const auth=await authorize(request,env);
  if(auth.status!==200)return send(auth.status,{ok:false,error:auth.status===503?"private_inbox_not_configured":"access_denied",...(auth.reason?{reason:auth.reason}:{})});
  if(!env.AMICOR_LEADS)return send(503,{ok:false,error:"lead_store_unavailable"});
  try{
    const records=[];
    let cursor=undefined,complete=false,pages=0;
    do{
      const opts={prefix:"lead:",limit:1000};
      if(cursor)opts.cursor=cursor;
      const page=await env.AMICOR_LEADS.list(opts);
      records.push(...page.keys.filter(k=>k.name.startsWith("lead:")));
      cursor=page.list_complete?undefined:page.cursor;
      complete=page.list_complete===true;
      pages++;
    }while(cursor&&pages<5);
    records.sort((a,b)=>b.name.localeCompare(a.name));
    const selected=records.slice(0,100);
    const rows=[];
    for(let i=0;i<selected.length;i+=10){
      const batch=selected.slice(i,i+10);
      const data=await Promise.all(batch.map(async k=>{try{return {key:k.name,value:await env.AMICOR_LEADS.get(k.name,{type:"json"})};}catch{return null;}}));
      for(const r of data){
        if(!r||!r.value||r.value.consent!==true||r.value.product!=="Nova Growth Agent")continue;
        const p=r.value;
        const limit=(v,n)=>String(v??"").slice(0,n);
        rows.push({key:r.key,receivedAt:limit(p.receivedAt,40),name:limit(p.name,120),
          company:limit(p.company,160),email:limit(p.email,254),phone:limit(p.phone,40),
          product:limit(p.product,80),message:limit(p.message,2000),
          status:"needs_review"});
      }
    }
    return send(200,{ok:true,source:"AMICOR_LEADS",complete,rows});
  }catch{return send(503,{ok:false,error:"lead_store_unavailable"});}
}
