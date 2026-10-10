const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

test('browser dictation restarts after pauses, appends words, and waits for explicit submission', () => {
  function node() { return {dataset:{},children:[],handlers:{},setAttribute(k,v){this[k]=v;},appendChild(x){this.children.push(x);},addEventListener(k,fn){this.handlers[k]=fn;},querySelector(){return this.children.find(x=>x['data-nova-voice-status']);}}; }
  const input = {value:'Earlier request'};
  const form = node(); form.id='ask-form';
  let submissions=0;
  form.querySelector = selector => selector.includes('#ask-input') ? input : null;
  form.requestSubmit = () => submissions++;
  let recognition;
  class Recognition { constructor(){recognition=this;this.starts=0;} start(){this.starts++;} abort(){this.onend();} }
  let timers=[];
  const window = {location:{search:''},SpeechRecognition:Recognition,setTimeout(fn){timers.push(fn);return timers.length;},clearTimeout(){timers=[];}};
  const document = {readyState:'complete',documentElement:{getAttribute(){return 'so-SO';}},querySelectorAll(){return [form];},querySelector(){return null;},getElementById(){return null;},createElement:node};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/ux/novaVoiceControls.js'),'utf8'),{window,document,URLSearchParams});
  const controls=form.children[0];
  controls.children[0].handlers.click();
  assert.equal(recognition.continuous,true);
  const result = text => {const row=[{transcript:text}];row.isFinal=true;recognition.onresult({resultIndex:0,results:[row]});};
  result('Waxaan rabaa');
  recognition.onerror({error:'no-speech'});
  recognition.onend();
  assert.equal(submissions,0);
  timers.shift()();
  assert.equal(recognition.starts,2);
  result('liiska tababarka');
  assert.equal(input.value,'Earlier request Waxaan rabaa liiska tababarka');
  controls.children[2].handlers.click();
  assert.equal(submissions,0);
  assert.equal(timers.length,0);
  controls.children[1].handlers.click();
  assert.equal(submissions,1);
});
