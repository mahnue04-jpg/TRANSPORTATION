// Run: node --test tools/check_studio_project_brief.js
// Executes the actual UI functions with local DOM/API adapters; no browser or network.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../backend/static/nova-creative/creative.js'), 'utf8');

function actualFunction(name) {
  const start = source.indexOf('  function ' + name + '(');
  assert.ok(start >= 0);
  const end = source.indexOf('\n  function ', start + 1);
  return source.slice(start, end);
}

function setup() {
  const fields = Object.fromEntries(['brief-topic', 'brief-cta', 'brief-style'].map(id =>
    [id, { value: '', disabled: false }]));
  let submit;
  fields['brief-form'] = { addEventListener: (event, handler) => { submit = handler; } };
  const calls = [], messages = [], outputs = [];
  for (const [id, value] of Object.entries({ 'project-platform': 'YouTube',
    'project-audience': 'Families', 'project-tone': 'Gentle', 'project-duration': '30' })) {
    fields[id] = {value};
  }
  const context = vm.createContext({
    activeProjectId: null, activeProjectRevision: 0, briefProjectId: null,
    presenterScriptProjectId: null, presenterSavedScriptValue: null, activeProjectKey: 'project',
    $: id => fields[id], localStorage: { setItem() {}, removeItem() {} },
    updateActiveProjectLabel() {}, renderPreflight() {}, renderProductionReadiness() {},
    api: async (url, options) => { calls.push({url, payload: JSON.parse(options.body)}); return {}; },
    showBanner: (...args) => messages.push(args), renderOutput: row => outputs.push(row),
  });
  const start = source.indexOf('  $("brief-form").addEventListener');
  const end = source.indexOf('  function presenterPayload()', start);
  assert.ok(start >= 0 && end > start);
  vm.runInContext(actualFunction('setActiveProjectId') + actualFunction('syncContentBrief') +
                  source.slice(start, end), context);
  const select = id => context.setActiveProjectId(id);
  const load = (id, brief, revision = context.activeProjectRevision) =>
    context.syncContentBrief({project: {id}, brief}, id, revision);
  return {context, fields, calls, messages, outputs, select, load,
    submit: () => submit({preventDefault() {}})};
}

test('switching projects clears old content, then loads the selected saved brief', () => {
  const s = setup();
  s.select('education');
  s.load('education', {topic: 'Count apples', cta: 'Count together', style: 'Illustrated lesson'});
  s.select('drama');
  assert.equal(s.fields['brief-topic'].value, '');
  assert.equal(s.fields['brief-topic'].disabled, true);
  s.load('drama', {topic: 'Missing notebook', cta: 'To be continued', style: 'Realistic drama'});
  assert.equal(s.fields['brief-topic'].value, 'Missing notebook');
  assert.equal(s.fields['brief-cta'].value, 'To be continued');
  assert.equal(s.fields['brief-style'].value, 'Realistic drama');
  assert.equal(s.fields['brief-topic'].disabled, false);
});

test('same-project refresh preserves unsaved edits', () => {
  const s = setup();
  s.select('cartoon');
  s.load('cartoon', {topic: 'Share apples'});
  s.fields['brief-topic'].value = 'Share four apples equally';
  s.load('cartoon', {topic: 'Share apples'});
  assert.equal(s.fields['brief-topic'].value, 'Share four apples equally');
});

test('a project without a brief receives empty fields rather than another project copy', () => {
  const s = setup();
  s.select('education'); s.load('education', {topic: 'Apples', cta: 'Count', style: '2D'});
  s.select('empty'); s.load('empty', null);
  for (const id of ['brief-topic', 'brief-cta', 'brief-style']) assert.equal(s.fields[id].value, '');
});

test('late responses cannot replace content after switching away and back', () => {
  const s = setup();
  s.select('education');
  const oldRevision = s.context.activeProjectRevision;
  s.select('drama'); s.select('education');
  s.load('education', {topic: 'Stale response'}, oldRevision);
  assert.equal(s.fields['brief-topic'].value, '');
  assert.equal(s.fields['brief-topic'].disabled, true);
  s.load('education', {topic: 'Current lesson'});
  assert.equal(s.fields['brief-topic'].value, 'Current lesson');
});

test('saving before the selected brief loads performs no API write', async () => {
  const s = setup();
  s.select('education');
  await s.submit();
  assert.equal(s.calls.length, 0);
  assert.match(s.messages[0][0], /Wait for the selected project's saved brief/);
});

test('saving sends the correct project and fields; late success does not change another project', async () => {
  const s = setup();
  s.select('education'); s.load('education', {topic: 'Apples', cta: 'Count', style: '2D'});
  let resolve;
  s.context.api = (url, options) => {
    s.calls.push({url, payload: JSON.parse(options.body)});
    return new Promise(done => { resolve = done; });
  };
  const saving = s.submit();
  assert.equal(s.calls[0].payload.project_id, 'education');
  assert.equal(s.calls[0].payload.topic, 'Apples');
  s.select('drama'); s.load('drama', {topic: 'Notebook'});
  resolve({brief: 'education saved'});
  await saving;
  assert.equal(s.fields['brief-topic'].value, 'Notebook');
  assert.equal(s.outputs.length, 0);
  assert.equal(s.messages.length, 0);
});
