const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/creative.js', 'utf8');
const polling = source.slice(source.indexOf('  async function waitForScene('), source.indexOf('  async function waitForFinalPromo('));

test('saved motion failures render the provider reason safely after a project reload', async () => {
  const elements = {'asset-list': {innerHTML: ''}};
  const ctx = vm.createContext({
    activeProjectId: 'selected',
    $: id => elements[id],
    api: async () => ({assets: [
      {title: 'Scene 1', kind: 'video', status: 'ERROR', content: 'Hotel lobby', metadata: {provider_result: {message: 'Runway error 400: insufficient credits <script>alert(1)</script> Bearer secret-token'}}},
      {title: 'Dialogue', kind: 'audio', status: 'GENERATED', url: '/voice.mp3'},
    ]}),
    refreshDrama: () => {}, renderProductionReadiness: () => {},
    document: {querySelectorAll: () => []},
  });
  const escape = source.slice(source.indexOf('  function escapeHtml('), source.indexOf('  function loadImage('));
  const memoryNotice = source.slice(source.indexOf('  function memoryHeadroomNotice('), source.indexOf('  function assetFailureHtml('));
  const failure = source.slice(source.indexOf('  function assetFailureHtml('), source.indexOf('  async function downloadBrandedImage('));
  const refresh = source.slice(source.indexOf('  async function refreshAssets('), source.indexOf('  async function waitForScene('));
  // refreshAssets is followed by event registration; isolate its declaration.
  const end = refresh.indexOf('\n  $("reset-project-media")');
  vm.runInContext(escape + memoryNotice + failure + (end >= 0 ? refresh.slice(0, end) : refresh), ctx);
  await ctx.refreshAssets();
  const html = elements['asset-list'].innerHTML;
  assert.match(html, /insufficient credits/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>|secret-token/);
  assert.match(html, /Download voice/);
});

function context(responses) {
  const calls = [];
  const ctx = vm.createContext({
    activeProjectId: 'selected',
    setTimeout: (cb) => cb(),
    api: async (path) => { calls.push(path); const response = responses.shift(); if (response instanceof Error) throw response; return response; },
    showBanner: () => {}, refreshAssets: async () => {},
  });
  vm.runInContext(polling, ctx);
  return {ctx, calls};
}

test('polling ignores an older job and returns the asset of the requested job', async () => {
  const {ctx, calls} = context([
    {jobs: [{id: 'old', status: 'GENERATED'}, {id: 'new', status: 'RUNNING'}]},
    {jobs: [{id: 'new', status: 'GENERATED', result_asset_ids: ['scene2']}], assets: [{id: 'scene1', url: 'old.mp4'}, {id: 'scene2', url: 'new.mp4', metadata: {provider_result: {status: 'GENERATED'}}}]},
  ]);
  const result = await ctx.waitForScene('selected', 'new');
  assert.equal(result.url, 'new.mp4');
  assert.equal(result.provider.status, 'GENERATED');
  assert.equal(calls.length, 2);
  assert.ok(calls.every(path => path.endsWith('/selected')));
});

test('worker errors surface their reason instead of a success banner', async () => {
  const {ctx} = context([{jobs: [{id: 'new', status: 'ERROR', message: 'Runway credits unavailable'}]}]);
  await assert.rejects(ctx.waitForScene('selected', 'new'), /Runway credits unavailable/);
});

test('project switching does not change the job being polled', async () => {
  const {ctx, calls} = context([{jobs: [{id: 'new', status: 'GENERATED', result_asset_ids: []}]}]);
  ctx.activeProjectId = 'other-project';
  await ctx.waitForScene('original-project', 'new');
  assert.equal(calls[0], '/api/nova/creative/projects/original-project');
  assert.equal(ctx.activeProjectId, 'other-project');
});

function transientError(status) {
  return Object.assign(new Error('Temporary system error. (' + status + ')'), {status, retryable: true});
}

test('a gateway failure reconnects to the same job and retrieves its completed clip', async () => {
  const {ctx, calls} = context([
    transientError(502),
    {jobs: [{id: 'new', status: 'RUNNING'}]},
    transientError(503),
    {jobs: [{id: 'new', status: 'GENERATED', result_asset_ids: ['clip']}], assets: [{id: 'clip', url: 'done.mp4'}]},
  ]);
  ctx.refreshAssets = async () => { throw new Error('redundant fetch must not interrupt polling'); };
  const result = await ctx.waitForScene('selected', 'new');
  assert.equal(result.url, 'done.mp4');
  assert.equal(calls.length, 4);
  assert.ok(calls.every(path => path === '/api/nova/creative/projects/selected'));
});

test('persistent connection failures report unknown job state, not generation failure', async () => {
  const {ctx, calls} = context(Array.from({length: 12}, () => transientError(502)));
  await assert.rejects(ctx.waitForScene('selected', 'new'), /job new.*result is unknown/);
  assert.equal(calls.length, 12);
});

test('session expiry is surfaced immediately without retries', async () => {
  const {ctx, calls} = context([new Error('Session expired. Sign in again. (401)')]);
  await assert.rejects(ctx.waitForScene('selected', 'new'), /Session expired/);
  assert.equal(calls.length, 1);
});

test('HTTP API marks gateway and network failures retryable but preserves session errors', async () => {
  const apiSource = source.slice(source.indexOf('  async function api('), source.indexOf('  function setSignedIn('));
  const ctx = vm.createContext({token: () => null, detailText: (_body, fallback) => fallback});
  vm.runInContext(apiSource, ctx);
  ctx.fetch = async () => ({status: 502, ok: false, json: async () => null});
  await assert.rejects(ctx.api('/status'), err => err.status === 502 && err.retryable === true);
  ctx.fetch = async () => { throw new Error('connection reset'); };
  await assert.rejects(ctx.api('/status'), err => err.retryable === true);
  ctx.fetch = async () => ({status: 401, ok: false, json: async () => null});
  await assert.rejects(ctx.api('/status'), err => !err.retryable && /401/.test(err.message));
});


test('sign-in uses one unauthenticated request and surfaces the login error without clearing the project session', async () => {
  const apiSource = source.slice(source.indexOf('  async function api('), source.indexOf('  function setSignedIn('));
  const calls = [];
  const ctx = vm.createContext({
    window: {AmiCorSession: {ensureReady: async () => { throw new Error('login must not refresh the old session'); }, authFetch: async () => { throw new Error('login must not replay through authFetch'); }}},
    token: () => 'old-token',
    detailText: body => body.detail,
    setToken: () => { throw new Error('login rejection must not clear the existing session'); },
    setSignedIn: () => { throw new Error('login rejection is not session expiry'); },
    fetch: async (path, options) => { calls.push({path, options}); return {status:401, ok:false, json:async () => ({detail:'Invalid email or password'})}; },
  });
  vm.runInContext(apiSource, ctx);
  await assert.rejects(ctx.api('/api/auth/login', {method:'POST',body:'test credentials fixture'}), /Sign-in failed.*Invalid email or password/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.headers.Authorization, undefined);
});
