'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'website-inquiries-preview.js'),'utf8');

function harness(fetchImpl, initialToken='owner-test-token') {
  class Element {
    constructor() { this.children=[];this.listeners={};this.textContent='';this.disabled=false; }
    addEventListener(type, handler) { this.listeners[type]=handler; }
    replaceChildren(...items) { this.children=items; }
    append(...items) { this.children.push(...items); }
  }
  const ids = ['website-inquiries-preview-load','website-inquiries-preview-status','website-inquiries-preview-list','sign-out','login-form'];
  const nodes = Object.fromEntries(ids.map(id=>[id,new Element()]));
  let token=initialToken;
  const storageListeners={};
  const ctx = {
    document: { getElementById: id => nodes[id]||null, createElement:()=>new Element() },
    localStorage: {getItem:()=>token},
    window: { addEventListener:(type,cb)=>{storageListeners[type]=cb;} },
    fetch:fetchImpl,
    Error,
  };
  vm.runInNewContext(source,ctx,{timeout:1000});
  return {nodes, storageListeners, setToken(value) { token=value; }, click() {return nodes['website-inquiries-preview-load'].listeners.click();}};
}
const synthetic = {status:'synthetic_preview',production_kv_connected:false,inquiries:[
 {company:'Fictional Example',product:'Business Services',status:'needs_owner_review',is_synthetic:true},
 {company:'SHOULD NOT SHOW',is_synthetic:false},
]};
test('signed-in synthetic inquiry renders once, never shows non-synthetic rows',async()=>{
  let calls=0;
  const ui=harness(async (url,opts)=>{
    calls++;
    assert.equal(url,'/api/nova/growth-agent/website-inquiries/preview');
    assert.equal(opts.headers.Authorization,'Bearer owner-test-token');
    return {ok:true,json:async()=>synthetic};
  });
  await ui.click();
  assert.equal(calls,1);
  assert.match(ui.nodes['website-inquiries-preview-status'].textContent,/Synthetic example only/);
  const rows=ui.nodes['website-inquiries-preview-list'].children;
  assert.equal(rows.length,1);
  assert.equal(rows[0].children[0].textContent,'Fictional Example');
});
test('missing token never sends request',async()=>{
  let calls=0;
  const ui=harness(async()=>{calls++;return {ok:true,json:async()=>synthetic};},'');
  await ui.click();
  assert.equal(calls,0);
  assert.match(ui.nodes['website-inquiries-preview-status'].textContent,/sign-in required/i);
});
test('sign-out invalidates a pending result',async()=>{
  let release;
  const ui=harness(()=>new Promise(resolve=>{release=resolve;}));
  const pending=ui.click();
  ui.setToken('');
  ui.nodes['sign-out'].listeners.click();
  release({ok:true,json:async()=>synthetic});
  await pending;
  assert.equal(ui.nodes['website-inquiries-preview-list'].children.length,0);
});
test('401 and source unavailable do not display any inquiry',async()=>{
  const ui=harness(async()=>({ok:false,status:401}));
  await ui.click();
  assert.equal(ui.nodes['website-inquiries-preview-list'].children.length,0);
  assert.match(ui.nodes['website-inquiries-preview-status'].textContent,/Sign in again/);
});
