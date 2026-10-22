const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function boot() {
  const window = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/nova-language/preference.js'), 'utf8'), {
    window,
    localStorage: {getItem: () => '', setItem() {}},
    fetch: async () => ({ok: false, json: async () => ({})})
  });
  return window.AmiCorLanguage;
}

const samples = {
  ja: '請求書を確認し、client approval を待ってください。Governing law applies.',
  ko: '인보이스를 확인하고 client approval 을 기다리세요. Governing law applies.',
  el: 'Ελέγξτε το τιμολόγιο και περιμένετε client approval. Governing law applies.',
  ru: 'Проверьте счёт и дождитесь client approval. Governing law applies.',
  de: 'Prüfen Sie die Rechnung und warten Sie auf client approval. Governing law applies.'
};

test('each rollout language keeps the task and refuses legal and approval translation', () => {
  const api = boot();
  for (const code of ['ja', 'ko', 'el', 'ru', 'de']) {
    const guard = api.guardTask(samples[code], code);
    assert.equal(guard.output_text, samples[code]);
    assert.equal(guard.source_language, code);
    assert.equal(guard.translation_applied, false);
    assert.equal(guard.legal_terms_present, true);
    assert.equal(guard.legal_terms_translated, false);
    assert.equal(guard.client_approval_present, true);
    assert.equal(guard.client_approval_translated, false);
    assert.equal(guard.business_delivery_operational, false);
    assert.equal(guard.operational, false);
    assert.equal(guard.unsupported_translation_refused, true);
    assert.match(guard.notice, /\S/);
    assert.match(guard.approval_copy.legal_not_translated, /\S/);
    assert.match(guard.approval_copy.client_approval_not_translated, /\S/);
    assert.equal(guard.approval_copy.approval_is_not_execution.length > 0, true);
  }
});

test('a verified screen language still does not translate legal or approval text', () => {
  const guard = boot().guardTask('French contract support. Governing law and client approval required.', 'fr');
  assert.equal(guard.translation_applied, false);
  assert.equal(guard.legal_terms_translated, false);
  assert.equal(guard.client_approval_translated, false);
  assert.equal(guard.business_delivery_operational, true);
  assert.equal(guard.output_text.includes('Governing law'), true);
});

test('a response that calls a rollout language operational is not applied', async () => {
  const storage = {amicor_nova_screen_language: 'es'};
  const window = {
    AmiCorSession: {
      getAccessToken: () => 'session-token',
      getAuthHeaders: () => ({Authorization: 'Bearer session-token'})
    }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/nova-language/preference.js'), 'utf8'), {
    window,
    localStorage: {
      getItem: (key) => storage[key] || '',
      setItem: (key, value) => { storage[key] = value; }
    },
    fetch: async () => ({ok: true, json: async () => ({
      screen_language: 'ja',
      operational: true,
      business_delivery_operational: true,
      translation_verified: true,
      voice_interpretation: false,
      bidirectional_text: false
    })})
  });
  assert.equal(await window.AmiCorLanguage.pull(), 'es');
  assert.equal(storage.amicor_nova_screen_language, 'es');
});

test('Work and Operations surfaces expose the rollout languages as planned', () => {
  const root = path.join(__dirname, '../static');
  const files = [
    'nova-home/index.html',
    'nova-workspace/index.html',
    'nova-synapse/index.html',
    'nova-work/index.html',
    'nova-anonymous-agent/index.html'
  ];
  for (const file of files) {
    const html = fs.readFileSync(path.join(root, file), 'utf8');
    for (const code of ['ja', 'ko', 'el', 'ru', 'de']) {
      assert.match(html, new RegExp('value="' + code + '" data-rollout="planned"'));
    }
    assert.match(html, /Business delivery in those languages is not verified/);
    assert.doesNotMatch(html, /operational in Japanese|operational in Korean|operational in Greek|operational in Russian|operational in German/i);
  }
  const work = fs.readFileSync(path.join(root, 'nova-work/index.html'), 'utf8');
  const agent = fs.readFileSync(path.join(root, 'nova-anonymous-agent/index.html'), 'utf8');
  assert.match(work, /nova-language\/preference\.js/);
  assert.match(agent, /nova-language\/preference\.js/);
  assert.match(agent, /id="demo-language-guard"/);
});
