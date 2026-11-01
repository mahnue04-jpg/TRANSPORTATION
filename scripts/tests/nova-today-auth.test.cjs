const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'backend/static/nova-today/index.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'backend/static/nova-today/today.js'), 'utf8');

function harness(restored) {
  const elements = new Map(), timers = [];
  function element(id) {
    const tag = html.match(new RegExp('<[^>]*\\bid="' + id + '"[^>]*>'));
    const classes = new Set(((tag && tag[0].match(/class="([^"]*)"/) || [])[1] || '').split(/\s+/));
    return { value: '', textContent: '', innerHTML: '', handlers: {}, attributes: {},
      classList: {
        add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
        contains(name) { return classes.has(name); },
        toggle(name, force) {
          const on = force === undefined ? !classes.has(name) : force;
          if (on) classes.add(name); else classes.delete(name);
          return on;
        }
      },
      setAttribute(name, value) { this.attributes[name] = value; },
      addEventListener(name, fn) { this.handlers[name] = fn; }, focus() {},
      querySelector() { return null; }
    };
  }
  function get(id) {
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  }
  let currentToken = '';
  const session = {
    restore() { currentToken = restored ? 'restored-token' : ''; },
    getAccessToken() { return currentToken; },
    getCurrent() { return { identity: { name: 'Owner' } }; },
    start(payload) { currentToken = payload.accessToken; },
    logout() { currentToken = ''; }
  };
  const document = { getElementById: get, body: element('body'),
    createElement: () => element('detached'), addEventListener() {},
    querySelectorAll: () => [], querySelector: () => null };
  const window = { AmiCorSession: session,
    setTimeout(fn) { timers.push(fn); }, localStorage: { getItem() { return null; }, setItem() {} } };
  vm.runInNewContext(source, { window, document, fetch: async url => ({
    status: 200, ok: true, json: async () => url === '/api/auth/login'
      ? { access_token: 'login-token', email: 'owner@example.test' } : {}
  }) });
  timers.forEach(fn => fn());
  return { get, flush: () => new Promise(resolve => setImmediate(resolve)) };
}

function assertControls(h, signedIn) {
  assert.equal(h.get('sign-in-toggle').classList.contains('hidden'), signedIn);
  assert.equal(h.get('sign-out').classList.contains('hidden'), !signedIn);
}

test('restored sign-in hides Sign in in compact and expanded views', async () => {
  const h = harness(true);
  await h.flush();
  assert.match(h.get('session-meta').textContent, /Owner/);
  assertControls(h, true);
  h.get('compact-toggle').handlers.click();
  assertControls(h, true);
});

test('login, logout and login again show only the appropriate auth control', async () => {
  const h = harness(false);
  await h.flush();
  assertControls(h, false);
  for (let n = 0; n < 2; n++) {
    h.get('sign-in-toggle').handlers.click();
    assert.equal(h.get('login-form').classList.contains('hidden'), false);
    h.get('login-email').value = 'owner@example.test';
    h.get('login-form').handlers.submit({ preventDefault() {} });
    await h.flush();
    assertControls(h, true);
    assert.equal(h.get('login-form').classList.contains('hidden'), true);
    h.get('sign-out').handlers.click();
    assertControls(h, false);
    assert.match(h.get('session-meta').textContent, /Sign in/);
  }
});
