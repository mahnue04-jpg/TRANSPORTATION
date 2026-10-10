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
      dispatchEvent(event) { if (this.handlers[event.type]) this.handlers[event.type](event); },
      setAttribute(k, v) { this[k] = v; }, appendChild() {},
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
    documentElement: { setAttribute() {} },
    getElementById: element,
    querySelectorAll: () => actions,
    addEventListener(type, fn) { if (type === 'click') click = fn; },
    createElement: () => element('created'),
  };
  const fetch = async (url, options = {}) => {
    requests.push({ url, body: typeof options.body === 'string' ? JSON.parse(options.body) : options.body });
    let data = {};
    if (url.endsWith('/dashboard')) data = { active_projects: Object.values(projects), assistant_history: [{ role: 'assistant', content: 'Saved draft', conversation_id: 'C' }] };
    else if (url.endsWith('/transfers')) data = options.method === 'POST' ? {transfer_id: 'T', status: 'pending', title: 'Timesheets', recipient_email: 'issa@example.com', conversation_count: 0, file_text_count: 0} : [];
    else if (url.endsWith('/transcribe')) data = { text: 'Waxaan rabaa liiska tababarka.' };
    else if (url.includes('/projects/')) data = projects[url.split('/').pop()];
    else if (url.includes('/conversations/')) data = { conversation_id: 'C', workspace_id: 'B', messages: [{ role: 'assistant', content: 'Saved timesheet draft' }] };
    else if (url.includes('/search?')) data = { hits: [{ kind: 'project', id: 'A', title: 'Onboarding', snippet: 'Tracker' }] };
    else if (url.endsWith('/ask')) data = { conversation_id: 'NEW', answer: 'Actual draft' };
    return { ok: true, status: 200, json: async () => data };
  };
  let tracksStopped = false;
  let microphoneConstraints;
  let recordingTimers = 0;
  class Recorder {
    constructor() { this.mimeType = 'audio/webm'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({data: new Blob(['audio'])}); this.onstop(); }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/nova-workspace/workspace.js'), 'utf8'), {
    document, fetch, Blob, Event, setTimeout(fn, ms) { if (ms === 60000) recordingTimers++; return setTimeout(fn, ms); }, clearTimeout, MediaRecorder: Recorder,
    navigator: { mediaDevices: { getUserMedia: async (constraints) => { microphoneConstraints = constraints; return { getTracks: () => [{ stop() { tracksStopped = true; } }] }; } } },
    FormData: class { append() {} }, window: { MediaRecorder: Recorder, addEventListener() {}, AmiCorSession: { getAccessToken: () => 'test', restore() {} } },
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
  element('answer-language').value = 'bilingual';
  await element('ask-form').handlers.submit({ preventDefault() {} });
  const request = requests.filter(r => r.url.endsWith('/ask')).at(-1).body;
  assert.equal(request.workspace_id, 'B');
  assert.equal(request.conversation_id, 'C');
  assert.equal(request.question, 'Revise this draft');
  assert.equal(request.answer_language, 'bilingual');
  assert.match(element('assistant-history').innerHTML, /data-open-convo="C"/);
  element('workspace-search').value = 'training';
  await element('workspace-search-form').handlers.submit({ preventDefault() {} });
  assert.match(element('search-results').innerHTML, /data-open-project="A"/);
  assert.match(element('brain-output').textContent, /Actual draft/);
  await open('data-open-project', 'A');
  await actions[0].handlers.click();
  assert.equal(requests.filter(r => r.url.endsWith('/ask')).at(-1).body.conversation_id, null);
  const asksBeforeRecording = requests.filter(r => r.url.endsWith('/ask')).length;
  await element('record-somali').handlers.click();
  assert.equal(recordingTimers, 0);
  assert.equal(microphoneConstraints.audio.noiseSuppression, true);
  await element('ask-form').handlers.submit({preventDefault() {}});
  assert.equal(requests.filter(r => r.url.endsWith('/ask')).length, asksBeforeRecording);
  element('finish-somali').handlers.click();
  await settle();
  assert.equal(element('ask-input').value, 'Waxaan rabaa liiska tababarka.');
  assert.equal(element('answer-language').value, 'so');
  assert.equal(tracksStopped, true);
  assert.equal(requests.filter(r => r.url.endsWith('/ask')).length, asksBeforeRecording);
  assert.match(element('recording-status').textContent, /Review or correct/);
  assert.equal(element('recording-status')['aria-busy'], 'false');
  assert.equal(element('finish-somali').disabled, true);
  assert.equal(element('record-somali').disabled, false);
  element('ask-input').value = 'Keep my earlier words';
  await element('record-somali').handlers.click();
  element('finish-somali').handlers.click();
  await settle();
  assert.match(element('ask-input').value, /^Keep my earlier words\nWaxaan/);
  assert.match(element('transfer-project').innerHTML, /Onboarding/);
  element('transfer-project').value = 'B';
  element('transfer-project').handlers.change();
  element('transfer-email').value = 'issa@example.com';
  await element('transfer-form').handlers.submit({preventDefault() {}});
  const offer = requests.filter(r => r.url.endsWith('/transfers') && r.body).at(-1).body;
  assert.equal(offer.workspace_id, 'B');
  assert.equal(offer.recipient_email, 'issa@example.com');
  element('answer-language').value = 'ar';
  element('answer-language').handlers.change();
  element('ask-input').value = 'قائمة التدريب';
  await element('ask-form').handlers.submit({preventDefault() {}});
  assert.equal(requests.filter(r => r.url.endsWith('/ask')).at(-1).body.answer_language, 'ar');
});
