const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function page(){
  const nodes={};
  function node(id){return nodes[id] ||= {value:'',textContent:'',className:'',listeners:{},attrs:{},classList:{add(){},remove(){},toggle(){}},addEventListener(type,fn){this.listeners[type]=fn;},focus(){this.focused=true;},getAttribute(name){return this.attrs[name];},setAttribute(name,value){this.attrs[name]=value;}};}
  const samples=['leads','data','documents'].map(key=>{const n=node(key);n.attrs['data-scenario']=key;return n;});
  const context={document:{getElementById:node,querySelectorAll:()=>samples},window:{location:{search:''}},URLSearchParams,Date,fetch(){throw Error('Sandbox must not call the network');}};
  vm.runInNewContext(fs.readFileSync(__dirname+'/agent.js','utf8'),context);
  node('demo-name').value='Jordan Lee';node('demo-business').value='Northstar';
  return {node,run(){node('run-operations-demo').listeners.click();},sample(key){node(key).listeners.click();}};
}
test('editable workflow chooses a data-specific next action without a network call',()=>{
 const p=page();p.sample('data');p.run();
 assert.match(p.node('demo-classification').textContent,/Spreadsheet & data/);
 assert.match(p.node('demo-record').textContent,/missing fields and duplicates/);
 assert.match(p.node('demo-report').textContent,/0 owner-review flags/);
});
test('owner approval is flagged even when the request is not urgent',()=>{
 const p=page();p.sample('documents');p.run();
 assert.match(p.node('demo-escalation').textContent,/owner decision/);
 assert.match(p.node('demo-report').textContent,/1 owner-review flag/);
});
test('empty input produces an accessible error and clears stale results',()=>{
 const p=page();p.node('demo-request').value=' ';p.run();
 assert.match(p.node('demo-summary').textContent,/Enter a request/);
 assert.equal(p.node('demo-request').focused,true);
});
test('user text is rendered literally rather than parsed as HTML',()=>{
 const p=page();p.node('demo-name').value='<img src=x onerror=alert(1)>';p.node('demo-request').value='urgent estimate';p.run();
 assert.match(p.node('demo-intake').textContent,/<img src=x/);
 assert.match(p.node('demo-summary').textContent,/Nothing was sent/);
});
