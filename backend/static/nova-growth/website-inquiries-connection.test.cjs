'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'website-inquiries-connection.js'), 'utf8');

function harness(fetchImpl, initialToken='test-owner-token') {
  class Element {
    constructor() { this.children=[];this.listeners={};this.textContent='';this.disabled=false; }
    addEventListener(type, cb) { this.listeners[type]=cb; }
    replaceChildren(...items) { this.children=items; }
    append(...items) { this.children.push(...items); }
  }
  const ids = ['website-inquiries-live-check','website-inquiries-live-status','website-inquiries-live-list','sign-out','login-form'];
  const nodes = Object.fromEntries(ids.map(x=>[x,new Element()]));
  let session=initialToken;
  vm.runInNewContext(source, {
    document:{getElementById:id=>nodes[id]||null,createElement:()=>new Element()},
    localStorage:{getItem:()=>session},
    window:{addEventListener:()=>{}},
    fetch:fetchImpl, Error, Number,
  });
  return {nodes,setToken:s=>session=s, click:()=>nodes['website-inquiries-live-check'].listeners.click()};
}

test('not-configured source shows disconnected not zero leads',async()=>{
  const ui=harness(async()=>({status:503,ok:false}));
  await ui.click();
  assert.match(ui.nodes['website-inquiries-live-status'].textContent,/Not connected/);
  assert.match(ui.nodes['website-inquiries-live-status'].textContent,/does not mean zero customer requests/i);
  assert.equal(ui.nodes['website-inquiries-live-list'].children.length,0);
});
test('missing session never calls API',async()=>{
  let calls=0;
  const ui=harness(async()=>{calls++;},'');
  await ui.click();
  assert.equal(calls,0);
  assert.match(ui.nodes['website-inquiries-live-status'].textContent,/Owner sign-in required/);
});
test('owner route requests read-only API without accepting raw HTML',async()=>{
  const ui=harness(async(url,opts)=>{
    assert.equal(url,'/api/nova/growth-agent/website-inquiries/read-only');
    assert.equal(opts.headers.Authorization,'Bearer test-owner-token');
    return {ok:true,status:200,json:async()=>({status:'ok',read_only:true,count:1,
      inquiries:[{company:'<script>alert(1)</script>',product:'Operations',status:'needs_owner_review',is_synthetic:false}]})};
  });
  await ui.click();
  const row=ui.nodes['website-inquiries-live-list'].children[0];
  assert.equal(row.children[0].textContent,'<script>alert(1)</script>');
  assert.match(row.children[1].textContent,/UNVERIFIED CUSTOMER RECORD/);
});
test('sign-out invalidates pending response and clears any list',async()=>{
  let finish;
  const ui=harness(()=>new Promise(resolve=>finish=resolve));
  const pending=ui.click();
  ui.setToken('');
  ui.nodes['sign-out'].listeners.click();
  finish({ok:true,status:200,json:async()=>({status:'ok',read_only:true,count:1,inquiries:[{company:'Example'}]})});
  await pending;
  assert.equal(ui.nodes['website-inquiries-live-list'].children.length,0);
});
test('incorrect count is rejected',async()=>{
  const ui=harness(async()=>({ok:true,status:200,json:async()=>({status:'ok',read_only:true,count:3,inquiries:[]})}));
  await ui.click();
  assert.match(ui.nodes['website-inquiries-live-status'].textContent,/incomplete/);
});
