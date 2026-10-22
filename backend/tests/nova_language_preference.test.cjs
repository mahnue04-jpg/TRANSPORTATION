const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function boot(options) {
  const storage = Object.assign({}, options.storage);
  const requests = [];
  const window = {AmiCorSession: options.session || null};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/nova-language/preference.js'), 'utf8'), {
    window,
    localStorage: {
      getItem: (key) => Object.prototype.hasOwnProperty.call(storage, key) ? storage[key] : '',
      setItem: (key, value) => { storage[key] = value; }
    },
    fetch: async (url, init) => {
      requests.push({url, init});
      return options.fetch(url, init);
    }
  });
  return {api: window.AmiCorLanguage, storage, requests};
}

test('signed-out preference stays on this device and does not call the account', async () => {
  let called = false;
  const state = boot({
    storage: {amicor_nova_screen_language: 'fr'},
    fetch: async () => { called = true; return {ok: true, json: async () => ({})}; }
  });
  assert.equal(await state.api.pull(), 'fr');
  assert.equal(called, false);
  const pushed = await state.api.push('es');
  assert.equal(pushed.persisted, false);
  assert.equal(pushed.voice_interpretation, false);
  assert.equal(pushed.bidirectional_text, false);
  assert.equal(state.storage.amicor_nova_screen_language, 'es');
  assert.equal(state.requests.length, 0);
});

test('signed-in preference follows the account and never sends a role', async () => {
  const state = boot({
    storage: {amicor_nova_screen_language: 'en'},
    session: {
      getAccessToken: () => 'session-token',
      getAuthHeaders: () => ({Authorization: 'Bearer session-token'})
    },
    fetch: async (url, init) => {
      if (!init || !init.method) return {ok: true, json: async () => ({screen_language: 'fr', persisted: true, voice_interpretation: false, bidirectional_text: false})};
      return {ok: true, json: async () => ({screen_language: 'ar', persisted: true, voice_interpretation: false, bidirectional_text: false})};
    }
  });
  assert.equal(await state.api.pull(), 'fr');
  assert.equal(state.requests[0].init.headers.Authorization, 'Bearer session-token');
  const saved = await state.api.push('ar');
  assert.equal(saved.screen_language, 'ar');
  assert.equal(JSON.parse(state.requests[1].init.body).screen_language, 'ar');
  assert.equal(JSON.parse(state.requests[1].init.body).role, undefined);
  assert.equal(state.storage.amicor_nova_screen_language, 'ar');
});

test('a response that claims live interpretation is not applied', async () => {
  const state = boot({
    storage: {amicor_nova_screen_language: 'es'},
    session: {getAccessToken: () => 'session-token', getAuthHeaders: () => ({Authorization: 'Bearer session-token'})},
    fetch: async () => ({ok: true, json: async () => ({screen_language: 'fr', voice_interpretation: true, bidirectional_text: false})})
  });
  assert.equal(await state.api.pull(), 'es');
  assert.equal(state.storage.amicor_nova_screen_language, 'es');
});

test('Nova Today reuses the workspace catalog and states the unavailable capabilities', () => {
  const home = fs.readFileSync(path.join(__dirname, '../static/nova-home/index.html'), 'utf8');
  const workspace = fs.readFileSync(path.join(__dirname, '../static/nova-workspace/index.html'), 'utf8');
  const synapse = fs.readFileSync(path.join(__dirname, '../static/nova-synapse/index.html'), 'utf8');
  for (const html of [home, workspace, synapse]) assert.match(html, /nova-language\/preference\.js/);
  assert.match(home, /data-nova-i18n="Workspace"/);
  assert.match(home, /Live voice interpretation is not available/);
  assert.match(home, /Bidirectional conversation translation is not available yet/);
  assert.match(home, /data-rollout="planned"/);
  assert.match(home, /Business delivery in those languages is not verified/);
  assert.doesNotMatch(home, /Japanese is operational/);
});
