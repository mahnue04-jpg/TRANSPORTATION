const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname,'../../static/nova-work/prospect-review.js'),'utf8');

class Element {
  constructor(){this.hidden=true;this.disabled=false;this.value='';this.textContent='';this.children=[];this.listeners={};this.submit=new Object();}
  addEventListener(name,fn){this.listeners[name]=fn;}
  querySelector(){if(!this.submit.disabled)this.submit.disabled=false;return this.submit;}
  replaceChildren(...children){this.children=children;}
  append(...children){this.children.push(...children);}
  appendChild(child){this.children.push(child);}
  click(){}
  remove(){}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function setup(fetcher,auth=true){
  const elements=new Map();const events={};const stored=new Map();const calls=[];
  const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const win={AmiCorSession:{getAuthHeaders:()=>auth?{Authorization:'Bearer synthetic-fixture'}:{}},crypto:{randomUUID:()=> 'synthetic-key-0001'},addEventListener:(name,fn)=>events[name]=fn};
  const context={window:win,document:{getElementById:el,createElement:()=>new Element(),body:new Element()},sessionStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)},URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL(){}},setTimeout:()=>{},fetch:async(url,opts)=>{calls.push({url,opts});return fetcher(url,opts);}};
  vm.runInNewContext(source,context);
  return {el,events,stored,calls,submit:id=>el(id).listeners.submit({preventDefault(){}})};
}
function response(body,status=200){return {ok:status===200,status,json:async()=>body,blob:async()=>Buffer.from('synthetic CSV')};}
const result={job_id:'a'.repeat(32),summary:{workflow_candidates:1,insufficient_evidence:0},source_failures:[],records:[{business:'Synthetic business',source_url:'https://example.com',checked_at:'2026-11-13',evidence:[{excerpt:'Public consultation workflow'}],status:'WORKFLOW_FIT_REQUIRES_QUALIFICATION',next_action:'Owner review'}]};

test('signed-out panel makes no network request',async()=>{
  const h=setup(()=>{throw Error('must not fetch');},false);await flush();
  assert.equal(h.el('prospect-review-panel').hidden,true);assert.equal(h.calls.length,0);
});
test('research retry keeps request identity and shows review-only output',async()=>{
  const h=setup(url=>response(url.endsWith('readiness')?{enabled:true}:result));await flush();
  h.el('prospect-discovery-query').value='Minnesota travel agencies';
  await h.submit('prospect-discovery-form');await h.submit('prospect-discovery-form');
  const calls=h.calls.filter(c=>c.url.endsWith('/discover'));
  assert.equal(calls.length,2);assert.equal(JSON.parse(calls[0].opts.body).request_key,JSON.parse(calls[1].opts.body).request_key);
  assert.equal(h.el('prospect-review-records').children.length,1);
  assert.match(h.el('prospect-review-status').textContent,/Buying interest unverified/);
  assert.equal(h.el('prospect-review-download').disabled,false);
});
test('late research response after sign-out cannot restore records or a download',async()=>{
  let release;const held=new Promise(resolve=>release=resolve);
  const h=setup(url=>url.endsWith('readiness')?response({enabled:true}):held);await flush();
  h.el('prospect-discovery-query').value='Minnesota travel agencies';
  const pending=h.submit('prospect-discovery-form');await flush();h.events['amicor:session-invalid']();
  release(response(result));await pending;
  assert.equal(h.el('prospect-review-panel').hidden,true);
  assert.equal(h.el('prospect-review-records').children.length,0);
  assert.equal(h.el('prospect-review-download').disabled,true);
  assert.equal(h.stored.has('nova-prospect-review-job'),false);
});
test('provider failure leaves controls usable and does not show fake output',async()=>{
  const h=setup(url=>url.endsWith('readiness')?response({enabled:true}):response({detail:'Search provider unavailable'},503));await flush();
  h.el('prospect-discovery-query').value='Minnesota travel agencies';await h.submit('prospect-discovery-form');
  assert.equal(h.el('prospect-discovery-form').submit.disabled,false);
  assert.equal(h.el('prospect-review-records').children.length,0);
  assert.equal(h.el('prospect-review-download').disabled,true);
  assert.match(h.el('prospect-review-status').textContent,/provider unavailable/);
});
