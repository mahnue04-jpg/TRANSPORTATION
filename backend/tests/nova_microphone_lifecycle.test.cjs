const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/ux/novaVoiceControls.js'), 'utf8');

function harness() {
  function node() {
    return {dataset:{},children:[],handlers:{},attrs:{},
      setAttribute(k,v){this.attrs[k]=v;},appendChild(x){this.children.push(x);},
      addEventListener(k,fn){this.handlers[k]=fn;},
      querySelector(){return this.children.find(x=>x.attrs['data-nova-voice-status']);}};
  }
  const input={value:'Existing words'}, form=node(), instances=[], timers=new Map();
  form.id='command-form';
  form.querySelector=s=>s.includes('#command-input')?input:null;
  let submitted=0, nextTimer=0;
  form.requestSubmit=()=>submitted++;
  class Recognition {
    constructor(){this.starts=0;this.aborts=0;this.stops=0;instances.push(this);}
    start(){this.starts++;}
    stop(){this.stops++;}
    abort(){this.aborts++;this.onerror({error:'aborted'});this.onend();}
  }
  const window={location:{search:''},SpeechRecognition:Recognition,
    setTimeout(fn){timers.set(++nextTimer,fn);return nextTimer;},
    clearTimeout(id){timers.delete(id);}};
  const document={readyState:'complete',documentElement:{getAttribute(){return 'en-US';}},
    querySelectorAll(){return [form];},querySelector(){return null;},
    getElementById(){return null;},createElement:node};
  vm.runInNewContext(source,{window,document,URLSearchParams});
  const controls=form.children[0], status=controls.children[3];
  return {input,instances,status,window,
    talk:()=>controls.children[0].handlers.click(),
    start:()=>controls.children[1].handlers.click(),
    stop:()=>controls.children[2].handlers.click(),
    get submitted(){return submitted;},
    runTimers(){const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());},
    words(rec,text){const row=[{transcript:text}];row.isFinal=true;rec.onresult({resultIndex:0,results:[row]});}};
}

test('Stop gracefully finishes dictation and keeps a final recognition result',()=>{
  const h=harness();h.talk();const rec=h.instances[0];
  h.words(rec,'first phrase');h.stop();
  assert.equal(rec.stops,1);assert.equal(rec.aborts,0);
  h.words(rec,'last phrase');rec.onend();h.runTimers();
  assert.equal(h.input.value,'Existing words first phrase last phrase');
  assert.equal(rec.starts,1);assert.equal(h.submitted,0);
  assert.match(h.status.textContent,/Review your words/);
});
test('intentional abort during Start Nova cannot overwrite Running with an error',()=>{
  const h=harness();h.talk();const rec=h.instances[0];h.start();
  assert.equal(rec.aborts,1);assert.equal(h.submitted,1);
  assert.equal(h.status.textContent,'Running…');
  rec.onerror({error:'aborted'});rec.onend();
  assert.equal(h.status.textContent,'Running…');
  assert.equal(h.input.value,'Existing words');
});
test('retired recognition cannot append stale text or change a new session status',()=>{
  const h=harness();h.talk();const old=h.instances[0];h.talk();
  const current=h.instances[1];
  old.onerror({error:'not-allowed'});h.words(old,'stale words');old.onend();
  assert.equal(h.status.textContent,'Listening… speak now.');
  assert.equal(h.input.value,'Existing words');
  h.words(current,'new words');
  assert.equal(h.input.value,'Existing words new words');
});
test('a real aborted session gives recovery guidance and can be started again',()=>{
  const h=harness();h.talk();const rec=h.instances[0];
  rec.onerror({error:'aborted'});rec.onend();h.runTimers();
  assert.match(h.status.textContent,/stopped unexpectedly/);
  assert.match(h.status.textContent,/Press Talk/);
  assert.equal(rec.starts,1);assert.equal(h.input.value,'Existing words');
  h.talk();assert.equal(h.instances[1].starts,1);
  h.words(h.instances[1],'recovered');
  assert.equal(h.input.value,'Existing words recovered');
});
test('permission errors remain visible after onend and do not auto restart',()=>{
  const h=harness();h.talk();const rec=h.instances[0];
  rec.onerror({error:'not-allowed'});rec.onend();h.runTimers();
  assert.match(h.status.textContent,/access was denied/);
  assert.equal(rec.starts,1);assert.equal(h.submitted,0);
});
test('an aborted callback during an intentional graceful stop is not an error',()=>{
  const h=harness();h.talk();const rec=h.instances[0];
  h.stop();rec.onerror({error:'aborted'});rec.onend();h.runTimers();
  assert.doesNotMatch(h.status.textContent,/error|unexpectedly/);
  assert.equal(h.input.value,'Existing words');
  assert.equal(rec.starts,1);
});
test('silence still restarts dictation without submitting the request',()=>{
  const h=harness();h.talk();const rec=h.instances[0];
  rec.onerror({error:'no-speech'});rec.onend();h.runTimers();
  assert.equal(rec.starts,2);assert.equal(h.submitted,0);
});
