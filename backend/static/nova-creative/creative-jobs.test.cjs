const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/creative.js', 'utf8');
const polling = source.slice(source.indexOf('  async function waitForScene('), source.indexOf('  async function waitForFinalPromo('));

function context(responses) {
  const calls = [];
  const ctx = vm.createContext({
    activeProjectId: 'selected',
    setTimeout: (cb) => cb(),
    api: async (path) => { calls.push(path); return responses.shift(); },
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
