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
    refresh: async () => {},
    window: { setTimeout(fn) { timer = fn; return 1; }, clearTimeout() { cleared = true; } }
  });
  // Execute the production request and submit functions, with only UI/transport adapters mocked.
  vm.runInContext(source.slice(source.indexOf('  function errorText('), source.indexOf('  function setSignedIn(')) +
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
