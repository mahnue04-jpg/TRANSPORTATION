const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../backend/static/nova-today/today.js'), 'utf8');

function harness(fetch, signedIn = true) {
  const elements = new Map();
  const button = { disabled: false, textContent: 'Ask Nova' };
  function $(id) {
    if (!elements.has(id)) elements.set(id, {
      value: '', textContent: '', attributes: {},
      setAttribute(k, v) { this.attributes[k] = v; },
      classList: { remove() {} }, focus() {}, querySelector() { return button; }
    });
    return elements.get(id);
  }
  let timer;
  let cleared = false;
  const context = vm.createContext({
    $, fetch, AbortController, selectedActionId: '', selectedSourceRefId: '',
    token: () => signedIn ? 'test-token' : '', session: () => null,
    showBanner: () => {}, hideBanner: () => {}, stopNovaSpeaking: () => {},
    setVoiceStatus: () => {}, renderBrainSources: () => {}, speakNova: () => {},
    renderBrainAnswer(result) { $('brain-output').textContent = (result.fact_label || 'AI SUGGESTION') + '\n\n' + result.answer; },
    refresh: async () => {},
    window: { setTimeout(fn) { timer = fn; return 1; }, clearTimeout() { cleared = true; } }
  });
  // Execute the production request and submit functions, with only UI/transport adapters mocked.
  vm.runInContext(source.slice(source.indexOf('  // One successful turn'), source.indexOf('  function identity(')) +
    source.slice(source.indexOf('  function errorText('), source.indexOf('  function setSignedIn(')) +
    source.slice(source.indexOf('  var brainBusy ='), source.indexOf('  async function decide(')), context);
  $('ask-input').value = 'what is the weather in Minneapolis today Mrs Nova';
  return { $, button, submit: () => context.runBrain({ preventDefault() {} }),
    timeout: () => timer(), cleared: () => cleared };
}
const response = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body });

test('pending request shows progress and suppresses duplicate submissions', async () => {
  let resolve, calls = 0;
  const h = harness(() => { calls++; return new Promise(r => { resolve = r; }); });
  const pending = h.submit();
  assert.equal(h.button.disabled, true);
  assert.match(h.$('brain-output').textContent, /working/);
  assert.equal(h.$('ask-form').attributes['aria-busy'], 'true');
  await h.submit();
  assert.equal(calls, 1);
  resolve(response(200, { answer: 'Current weather for Minneapolis: clear sky.' }));
  await pending;
  assert.match(h.$('brain-output').textContent, /clear sky/);
  assert.equal(h.$('ask-input').value, '');
  assert.equal(h.button.disabled, false);
  assert.equal(h.$('ask-form').attributes['aria-busy'], 'false');
  assert.equal(h.cleared(), true);
});

for (const status of [401, 403, 500]) {
  test(`HTTP ${status} error is displayed beside question and leaves it available to retry`, async () => {
    const h = harness(async () => response(status, {}));
    await h.submit();
    assert.match(h.$('brain-output').textContent, /Session expired|Access denied|Temporary system error/);
    assert.match(h.$('ask-input').value, /Minneapolis/);
    assert.equal(h.button.disabled, false);
  });
}

test('a stalled request is aborted and shows a retry message', async () => {
  const h = harness((url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
  }));
  const pending = h.submit();
  h.timeout();
  await pending;
  assert.match(h.$('brain-output').textContent, /too long.*try again/);
  assert.equal(h.button.disabled, false);
  assert.match(h.$('ask-input').value, /Minneapolis/);
});

test('network failure and empty response produce visible errors', async () => {
  for (const fetch of [async () => { throw new Error('offline'); }, async () => response(200, null)]) {
    const h = harness(fetch);
    await h.submit();
    assert.match(h.$('brain-output').textContent, /Network error|No response/);
    assert.equal(h.button.disabled, false);
  }
});

test('expired local sign-in is explained in the answer panel', async () => {
  const h = harness(() => assert.fail('must not fetch'), false);
  await h.submit();
  assert.match(h.$('brain-output').textContent, /Sign in/);
});

test('a new question typed during a request is preserved', async () => {
  let resolve;
  const h = harness(() => new Promise(r => { resolve = r; }));
  const pending = h.submit();
  h.$('ask-input').value = 'What is next?';
  resolve(response(200, { answer: 'Weather answer' }));
  await pending;
  assert.equal(h.$('ask-input').value, 'What is next?');
});


test('403 preserves the server explanation so an account restriction is actionable', async () => {
  const detail = 'Your 7-day AMICOR Nova trial has ended. Upgrade to continue using Ask Nova.';
  const h = harness(async () => response(403, { detail }));
  await h.submit();
  assert.equal(h.$('brain-output').textContent, detail);
  assert.equal(h.button.disabled, false);
});


test('follow-ups carry only the public sports topic and clear it after a private answer', async () => {
  const bodies = [];
  const replies = [
    {answer: 'Sourced public sports answer.', fact_label: 'LIVE WEB SOURCES', public_topic: 'Lions versus Vikings'},
    {answer: 'A private workspace answer.', fact_label: 'USER-SAVED INFORMATION', public_topic: 'must not retain this'},
    {answer: 'Another answer.'}
  ];
  const h = harness(async (url, options) => {
    bodies.push(JSON.parse(options.body));
    return response(200, replies.shift());
  });
  h.$('ask-input').value = 'Who will win between the Lions and the Vikings?';
  await h.submit();
  h.$('ask-input').value = 'Show my saved tasks';
  await h.submit();
  assert.equal(bodies[1].public_topic, 'Lions versus Vikings');
  h.$('ask-input').value = 'How can I watch the game for free?';
  await h.submit();
  assert.equal(bodies[2].public_topic, null);
  assert.equal(JSON.stringify(bodies).includes('A private workspace answer'), false);
  assert.equal(JSON.stringify(bodies).includes('must not retain this'), false);
});

test('viewing follow-up includes the previous public question, not the answer text', async () => {
  const bodies = [];
  const h = harness(async (url, options) => {
    bodies.push(JSON.parse(options.body));
    return response(200, {answer: 'Public answer with many details.', fact_label: 'LIVE WEB SOURCES', public_topic: 'Minnesota Timberwolves game'});
  });
  h.$('ask-input').value = 'Who is starting for the Timberwolves?';
  await h.submit();
  h.$('ask-input').value = 'Where can I watch it for free on my phone?';
  await h.submit();
  assert.equal(bodies[1].public_topic, 'Minnesota Timberwolves game');
  assert.equal(JSON.stringify(bodies).includes('Public answer with many details'), false);
});
