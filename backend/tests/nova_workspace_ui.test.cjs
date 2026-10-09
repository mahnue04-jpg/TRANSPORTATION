const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

test('project selection, action requests, reopened history and searchable results', async () => {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: '', textContent: '', innerHTML: '', handlers: {},
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener(type, fn) { this.handlers[type] = fn; },
      setAttribute() {}, appendChild() {},
      scrollIntoView() { this.scrolled = true; },
      focus() { this.focused = true; },
    });
    return elements.get(id);
  }
  const actions = ['continue', 'summarize', 'find_file', 'search_prior', 'explain_changed', 'next_action'].map(action => {
    const button = element(action);
    button.getAttribute = () => action;
    return button;
  });
  let click;
  const requests = [];
  const projects = { A: { workspace_id: 'A', title: 'Onboarding', description: 'Training tracker' }, B: { workspace_id: 'B', title: 'Timesheets' } };
  const document = {
    getElementById: element,
    querySelectorAll: () => actions,
    addEventListener(type, fn) { if (type === 'click') click = fn; },
    createElement: () => element('created'),
  };
  const fetch = async (url, options = {}) => {
    requests.push({ url, body: options.body && JSON.parse(options.body) });
    let data = {};
    if (url.endsWith('/dashboard')) data = { assistant_history: [{ role: 'assistant', content: 'Saved draft', conversation_id: 'C' }] };
    else if (url.includes('/projects/')) data = projects[url.split('/').pop()];
    else if (url.includes('/conversations/')) data = { conversation_id: 'C', workspace_id: 'B', messages: [{ role: 'assistant', content: 'Saved timesheet draft' }] };
    else if (url.includes('/search?')) data = { hits: [{ kind: 'project', id: 'A', title: 'Onboarding', snippet: 'Tracker' }] };
    else if (url.endsWith('/ask')) data = { conversation_id: 'NEW', answer: 'Actual draft' };
    return { ok: true, status: 200, json: async () => data };
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/nova-workspace/workspace.js'), 'utf8'), {
    document, fetch, FormData: class {}, window: { AmiCorSession: { getAccessToken: () => 'test', restore() {} } },
  });
  const settle = () => new Promise(resolve => setImmediate(resolve));
  await settle();
  const open = async (attribute, id) => click({ target: { closest: selector => selector === `[${attribute}]` ? { getAttribute: () => id } : null } });
  await open('data-open-project', 'A');
  assert.equal(element('selected-project').textContent, 'Selected project: Onboarding');
  assert.equal(element('workspace-command').scrolled, true);
  assert.equal(element('ask-input').focused, true);
  element('ask-input').value = 'Old unrelated request';
  for (const action of actions) {
    await action.handlers.click();
    const request = requests.filter(r => r.url.endsWith('/ask')).at(-1).body;
    assert.equal(request.workspace_id, 'A');
    assert.equal(request.question, null);
  }
  await open('data-open-convo', 'C');
  assert.equal(element('selected-project').textContent, 'Selected project: Timesheets');
  element('ask-input').value = 'Revise this draft';
  await element('ask-form').handlers.submit({ preventDefault() {} });
  const request = requests.filter(r => r.url.endsWith('/ask')).at(-1).body;
  assert.equal(request.workspace_id, 'B');
  assert.equal(request.conversation_id, 'C');
  assert.equal(request.question, 'Revise this draft');
  assert.match(element('assistant-history').innerHTML, /data-open-convo="C"/);
  element('workspace-search').value = 'training';
  await element('workspace-search-form').handlers.submit({ preventDefault() {} });
  assert.match(element('search-results').innerHTML, /data-open-project="A"/);
  assert.match(element('brain-output').textContent, /Actual draft/);
  await open('data-open-project', 'A');
  await actions[0].handlers.click();
  assert.equal(requests.filter(r => r.url.endsWith('/ask')).at(-1).body.conversation_id, null);
});
