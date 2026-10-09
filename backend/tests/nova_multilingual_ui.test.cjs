const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const root = __dirname + '/../static/nova-workspace/';

function localeContext(saved = 'en') {
  const attributes = {};
  const storage = {};
  const label = {textContent: '', getAttribute: () => 'Continue work'};
  const original = {textContent: 'Issa · PCA 15 minutes'};
  const select = {value: ''};
  const context = {
    Event, localStorage: {getItem: () => saved, setItem: (k,v) => storage[k] = v},
    window: {dispatchEvent() {}},
    document: {documentElement: {setAttribute: (k,v) => attributes[k] = v},
      getElementById: () => select,
      querySelectorAll: selector => selector === '[data-nova-i18n]' ? [label] : []}
  };
  vm.runInNewContext(fs.readFileSync(root + 'languages.js','utf8'), context);
  return {api: context.window.NovaWorkspaceLanguage, attributes, label, original, storage};
}

test('five screen languages, Arabic direction, persisted preference and untouched records', () => {
  const state = localeContext('ar');
  assert.equal(state.attributes.lang, 'ar');
  assert.equal(state.attributes.dir, 'rtl');
  assert.equal(state.label.textContent, 'تابع العمل');
  for (const code of ['so','fr','es','en']) {
    state.api.setLanguage(code);
    assert.equal(state.attributes.lang, code);
    assert.equal(state.attributes.dir, 'ltr');
    assert.equal(state.storage['nova-workspace-screen-language'], code);
    assert.equal(state.original.textContent, 'Issa · PCA 15 minutes');
  }
  state.api.setLanguage('ar');
  assert.equal(state.api.t('Selected project: {title}', {title:'Easy Care PCA'}), 'المشروع المحدد: Easy Care PCA');
});

test('every bound static interface label has all five translations', () => {
  const {api} = localeContext();
  const html = fs.readFileSync(root + 'index.html','utf8');
  const keys = [...html.matchAll(/data-nova-(?:i18n|placeholder|label)="([^"]*)"/g)].map(m => m[1].replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#x27;/g,"'"));
  for (const key of keys) {
    assert.ok(api.catalog[key] || key === 'Mrs. Nova Brain', 'missing interface translation: ' + key);
    if (api.catalog[key]) assert.equal(api.catalog[key].filter(Boolean).length, 5);
  }
});

function speechContext(fetch) {
  let source;
  let revoked = false;
  let shown = false;
  let message = '';
  let request;
  const audio = { pause() {}, removeAttribute() {},
    classList: {add() {shown=false;}, remove() {shown=true;}},
    set src(value) {source=value;}, play: async () => {throw new Error('NotAllowedError');}
  };
  const context = {
    AbortController, Blob, Uint8Array, atob,
    URL: {createObjectURL: () => 'blob:audio', revokeObjectURL: () => {revoked=true;}},
    fetch: async (url, options) => {request={url,options}; return fetch();},
    document: {getElementById: id => id === 'workspace-audio' ? audio : id === 'answer-language' ? {value:'ar'} : {set textContent(v){message=v;}}},
    window: {addEventListener() {}, NovaWorkspaceLanguage:{t: x=>x}, AmiCorSession: {getAuthHeaders:()=>({Authorization:'Bearer test'})}}
  };
  vm.runInNewContext(fs.readFileSync(root + 'speech.js','utf8'),context);
  return {api:context.window.NovaWorkspaceSpeech, snapshot:()=>({source,revoked,shown,message,request})};
}

test('Arabic audio request preserves native Play when browser blocks autoplay', async () => {
  const state = speechContext(async () => ({ok:true,json:async()=>({audio_b64:'SUQz',mime_type:'audio/mpeg'})}));
  await state.api.speak('مرحبا');
  const result=state.snapshot();
  assert.equal(JSON.parse(result.request.options.body).language,'ar');
  assert.equal(result.request.options.headers.Authorization,'Bearer test');
  assert.equal(result.shown,true);
  assert.equal(result.source,'blob:audio');
  assert.match(result.message,/Press Play/);
  state.api.stop();
  assert.equal(state.snapshot().shown,false);
  assert.equal(state.snapshot().revoked,true);
});

test('a stopped request cannot install stale audio', async () => {
  let resolve;
  const state=speechContext(()=>new Promise(r=>resolve=r));
  const speaking=state.api.speak('مرحبا');
  state.api.stop();
  resolve({ok:true,json:async()=>({audio_b64:'SUQz'})});
  await speaking;
  assert.equal(state.snapshot().shown,false);
  assert.equal(state.snapshot().source,undefined);
});

test('failed speech service keeps text and reports unavailability', async () => {
  const state=speechContext(async()=>({ok:false}));
  await state.api.speak('مرحبا');
  assert.equal(state.snapshot().shown,false);
  assert.match(state.snapshot().message,/Your text remains available/);
});
