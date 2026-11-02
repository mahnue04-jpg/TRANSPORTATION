const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/nova-government/government.js'), 'utf8');
function deferred() { let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b;}); return {promise,resolve,reject}; }
function harness({slowDashboard=false}={}) {
  const elements=new Map(), calls=[], timers=new Map(), dashboard=deferred(), answer=deferred();
  let access='fixture-token', nextTimer=0;
  function element(tag='div') {
    const classes=new Set();
    return {tag,children:[],handlers:{},attributes:{},value:'',disabled:false,_text:'',innerHTML:'',
      set textContent(value) {this._text=String(value);this.children=[];},
      get textContent() {return this._text+this.children.map(c=>c.textContent).join('');},
      classList:{add(x){classes.add(x);},remove(x){classes.delete(x);},contains(x){return classes.has(x);},
        toggle(x,force){const on=force===undefined?!classes.has(x):force;if(on)classes.add(x);else classes.delete(x);}},
      setAttribute(k,v){this.attributes[k]=v;}, addEventListener(k,v){this.handlers[k]=v;},
      appendChild(child){this.children.push(child);},focus(){this.focused=true;},scrollIntoView(){}};
  }
  function get(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
  const window={AmiCorSession:{restore(){},getAccessToken(){return access;},getCurrent(){return {identity:{name:'Fixture'}};},logout(){access='';}},
    location:{href:''},sessionStorage:{getItem(){return null;},setItem(){},removeItem(){}},
    setTimeout(fn,ms){const id=++nextTimer;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);}};
  const response=body=>({ok:true,status:200,json:async()=>body});
  async function fetch(url,options={}) {
    calls.push({url,options});
    if(url.endsWith('/dashboard')) return response(slowDashboard?await dashboard.promise:{});
    if(url.endsWith('/ask')) {
      const abort=deferred();
      if(options.signal)options.signal.addEventListener('abort',()=>abort.reject(new Error('aborted')),{once:true});
      return response(await Promise.race([answer.promise,abort.promise]));
    }
    throw new Error('Unexpected fixture request '+url);
  }
  const document={getElementById:get,createElement:element,querySelectorAll(){return [];},addEventListener(){}};
  vm.runInNewContext(source,{window,document,fetch,URL,AbortController});
  return {get,calls,timers,dashboard,answer,flush:()=>new Promise(r=>setImmediate(r)),
    submit:()=>get('ask-form').handlers.submit({preventDefault(){}})};
}
const result={fact_label:'OFFICIAL SOURCE EXCERPTS — APPLICABILITY NOT DETERMINED',answer:'Source-owned fixture passage',
  sources:[{url:'https://sam.gov/entity-registration',title:'Official fixture'}]};

test('question shows progress, submits once, retains text and renders clickable official sources',async()=>{
  const h=harness();await h.flush();h.get('ask-input').value='Research current government requirements using official sources.';
  const pending=h.submit();await h.flush();
  assert.match(h.get('brain-output').textContent,/working on your question/);
  assert.equal(h.get('ask-submit').disabled,true);
  assert.equal(h.get('brain-output').attributes['aria-busy'],'true');
  await h.submit();assert.equal(h.calls.filter(c=>c.url.endsWith('/ask')).length,1);
  const request=h.calls.find(c=>c.url.endsWith('/ask'));
  assert.equal(JSON.parse(request.options.body).question,h.get('ask-input').value);
  h.answer.resolve(result);await pending;
  assert.match(h.get('brain-output').textContent,/Source-owned fixture passage/);
  assert.equal(h.get('ask-submit').disabled,false);
  assert.equal(h.get('brain-output').attributes['aria-busy'],'false');
  assert.equal(h.timers.size,0);
  assert.equal(h.calls.filter(c=>c.url.endsWith('/dashboard')).length,1,'ordinary questions do not reload saved work');
  const link=h.get('brain-sources').children[0];
  assert.equal(link.href,'https://sam.gov/entity-registration');
  assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener noreferrer');
});

test('a slow startup dashboard cannot replace progress or a completed answer',async()=>{
  const h=harness({slowDashboard:true});h.get('ask-input').value='Public government question';
  const pending=h.submit();h.answer.resolve(result);await pending;
  h.dashboard.resolve({});await h.flush();
  assert.match(h.get('brain-output').textContent,/Source-owned fixture passage/);
  assert.doesNotMatch(h.get('brain-output').textContent,/connected to Nova Government/);
});

test('empty questions do not submit or pretend to be working',async()=>{
  const h=harness();await h.flush();await h.submit();
  assert.equal(h.calls.some(c=>c.url.endsWith('/ask')),false);
  assert.match(h.get('banner').textContent,/Enter a question/);
  assert.equal(h.get('ask-input').focused,true);
});

test('a timed out request releases controls and leaves the question available',async()=>{
  const h=harness();await h.flush();h.get('ask-input').value='Retained question';const pending=h.submit();await h.flush();
  const timeout=[...h.timers.values()][0];assert.equal(timeout.ms,45000);timeout.fn();await pending;
  assert.match(h.get('brain-output').textContent,/timed out/);
  assert.equal(h.get('ask-input').value,'Retained question');assert.equal(h.get('ask-submit').disabled,false);
});

test('source titles remain plain text and executable or credential-bearing URLs are discarded',async()=>{
  const h=harness();await h.flush();h.get('ask-input').value='Public question';const pending=h.submit();
  h.answer.resolve({...result,sources:[{url:'javascript:alert(1)',title:'Unsafe'},{url:'https://u:p@sam.gov/',title:'Credentials'},
    {url:'https://sam.gov/',title:'<img src=x onerror=fixture>'}]});await pending;
  assert.equal(h.get('brain-sources').children.length,1);
  assert.equal(h.get('brain-sources').children[0].textContent,'<img src=x onerror=fixture>');
});

test('an answer arriving after sign-out is not displayed',async()=>{
  const h=harness();await h.flush();h.get('ask-input').value='Public question';const pending=h.submit();await h.flush();
  await h.get('sign-out').handlers.click();h.answer.resolve({...result,answer:'Old session response'});await pending;
  assert.doesNotMatch(h.get('brain-output').textContent,/Old session response/);
  assert.equal(h.get('brain-sources').children.length,0);
  assert.equal(h.get('sign-in-toggle').classList.contains('hidden'),false);
  assert.equal(h.get('sign-out').classList.contains('hidden'),true);
});
