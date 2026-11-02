const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/creative.js', 'utf8');
const handler = source.slice(source.indexOf('  var finishedVideoForm ='), source.indexOf('  function renderOutput('));
const upload = source.slice(source.indexOf('  async function uploadBrowserFinalPromo('), source.indexOf('  function setSignedIn('));

function setup(options = {}) {
  let submit;
  const calls = [];
  const file = options.file || {name:'approved.mp4',type:'video/mp4',size:100};
  const elements = {
    'finished-video-import-form': {addEventListener: (_event, fn) => {submit = fn;}},
    'finished-video-file': {files:[file],value:'approved.mp4'},
    'import-finished-video': {disabled:false},
    'finished-video-import-status': {textContent:''},
  };
  const ctx = vm.createContext({
    activeProjectId: options.noProject ? null : 'original',
    projectRowsCache: [{id:'original',title:'Approved commercial'}],
    $: id => elements[id],
    token: () => options.signedOut ? '' : 'test-only',
    uploadBrowserFinalPromo: async (id, data) => {
      calls.push({id,data});
      if (options.duringUpload) await options.duringUpload(ctx);
      if (options.uploadError) throw new Error('network interrupted');
      return {asset:{id:'saved'}};
    },
    api: async path => {
      calls.push({path});
      return {assets:[{id:'saved',url:'/saved.mp4',media_available:!options.missing}]};
    },
    refreshAssets: async () => calls.push({refresh:true}),
    showBanner: () => {},
  });
  vm.runInContext(handler,ctx);
  return {ctx,calls,elements,submit:()=>submit({preventDefault(){}})};
}

test('import preserves the selected file and verifies its saved asset before success',async()=>{
  const h=setup(); await h.submit();
  assert.equal(h.calls[0].id,'original');
  assert.equal(h.calls[0].data.blob,h.elements['finished-video-file'].files[0]);
  assert.equal(h.calls[0].data.source,'owner_import');
  assert.equal(h.calls[1].path,'/api/nova/creative/projects/original');
  assert.match(h.elements['finished-video-import-status'].textContent,/Imported into Approved commercial/);
  assert.equal(h.elements['import-finished-video'].disabled,false);
});
test('switching projects during upload cannot change the destination or refresh the wrong project',async()=>{
  const h=setup({duringUpload:async ctx=>{ctx.activeProjectId='other';}}); await h.submit();
  assert.equal(h.calls[0].id,'original');
  assert.equal(h.calls[1].path,'/api/nova/creative/projects/original');
  assert.ok(!h.calls.some(c=>c.refresh));
});
test('repeated submit during upload does not send a second file',async()=>{
  let release; const waiting=new Promise(r=>{release=r;});
  const h=setup({duringUpload:()=>waiting}); const first=h.submit(); await h.submit();
  assert.equal(h.calls.length,1); release(); await first;
});
test('missing media is not reported as a successful playable import',async()=>{
  const h=setup({missing:true}); await h.submit();
  assert.match(h.elements['finished-video-import-status'].textContent,/verification failed/);
  assert.equal(h.calls.filter(c=>c.data).length,1);
});
test('unknown upload outcome is not retried automatically',async()=>{
  const h=setup({uploadError:true}); await h.submit();
  assert.match(h.elements['finished-video-import-status'].textContent,/not confirmed/);
  assert.equal(h.calls.length,1);
});
test('invalid files and missing project/session never send an upload',async()=>{
  for (const options of [{noProject:true},{signedOut:true},{file:{name:'clip.webm',type:'video/webm',size:1}},{file:{name:'clip.mp4',size:0}},{file:{name:'clip.mp4',size:151*1024*1024}}]) {
    const h=setup(options); await h.submit(); assert.equal(h.calls.length,0);
  }
});
test('multipart upload uses the shared session and no JSON content type or generation endpoint',async()=>{
  const requests=[]; const entries=[];
  const ctx=vm.createContext({
    FormData: class {append(...args){entries.push(args);}},
    window:{AmiCorSession:{ensureReady:async()=>{},authFetch:async(path,options)=>{
      requests.push({path,options});return {ok:true,json:async()=>({asset:{id:'saved'}})};
    }}},
    detailText:(_body,fallback)=>fallback,
  });
  vm.runInContext(upload,ctx);
  const blob={}; await ctx.uploadBrowserFinalPromo('original',{blob,fileName:'approved.mp4',source:'owner_import'});
  assert.equal(requests.length,1);
  assert.equal(requests[0].path,'/api/nova/creative/projects/original/assets/browser-final-promo');
  assert.equal(requests[0].options.headers,undefined);
  assert.equal(entries[0][1],blob);
  assert.deepEqual(entries[1],['source','owner_import']);
});
