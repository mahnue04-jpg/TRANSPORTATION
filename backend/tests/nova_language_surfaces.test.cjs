const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const pages = {
  today: 'static/nova-today/index.html',
  studio: 'static/nova-creative/index.html',
  'casting-preview': 'static/nova-creative/casting-preview.html',
  'casting-sandbox': 'static/nova-creative/casting-sandbox.html',
  snap: 'static/nova-communications/index.html'
};

function read(rel) {
  return fs.readFileSync(path.join(root, rel), 'utf8');
}

const css = read('static/nova-language/surface.css');
const surfaceSource = read('static/nova-language/surface.js');

test('each new surface shows the selector, fallback, and unverified notice', () => {
  for (const [surface, rel] of Object.entries(pages)) {
    const html = read(rel);
    assert.match(html, /name="viewport"/, surface);
    assert.match(html, /nova-language\/preference\.js/, surface);
    assert.match(html, /nova-language\/surface\.js/, surface);
    assert.match(html, /nova-language\/surface\.css/, surface);
    assert.match(html, new RegExp('data-nova-language-surface="' + surface + '"'));
    assert.match(html, /id="screen-language"/);
    assert.match(html, /id="language-fallback"/);
    assert.match(html, /If this screen cannot show the selected language, the original text stays in place/);
    assert.match(html, /Business delivery in those languages is not verified/);
    assert.match(html, /Live voice interpretation is not available/);
    assert.match(html, /Bidirectional conversation translation is not available yet/);
    for (const code of ['ja', 'ko', 'el', 'ru', 'de']) {
      assert.match(html, new RegExp('value="' + code + '" data-rollout="planned"'), surface + ' ' + code);
    }
    assert.doesNotMatch(html, /business_delivery_operational"?: true/);
    assert.doesNotMatch(html, /translation_verified"?: true/);
  }
});

test('mobile language control stays within the screen', () => {
  assert.match(css, /max-width:\s*100%/);
  assert.match(css, /min-height:\s*44px/);
  assert.match(css, /@media \(max-width:\s*640px\)/);
  assert.match(css, /font-size:\s*16px/);
  assert.match(css, /overflow-wrap:\s*anywhere/);
});

test('the binder does not touch credentials or mark rollout delivery operational', async () => {
  assert.doesNotMatch(surfaceSource, /password|Authorization|login-form|role/);
  const notice = {textContent: '', hidden: true};
  const fallback = {textContent: '', hidden: true};
  const select = {
    value: 'en',
    listeners: {},
    querySelector(selector) { return selector.indexOf('ja') >= 0 || selector.indexOf('en') >= 0 ? {} : null; },
    addEventListener(name, fn) { this.listeners[name] = fn; }
  };
  const doc = {
    documentElement: {lang: 'en', attrs: {}, setAttribute(name, value) { this.attrs[name] = value; }, getAttribute(name) { return this.attrs[name]; }},
    getElementById(id) {
      if (id === 'screen-language') return select;
      if (id === 'language-rollout-notice') return notice;
      if (id === 'language-fallback') return fallback;
      return null;
    }
  };
  const preference = fs.readFileSync(path.join(root, 'static/nova-language/preference.js'), 'utf8');
  const window = {};
  vm.runInNewContext(preference + '\n' + surfaceSource, {
    window,
    document: {readyState: 'complete', getElementById: () => null, addEventListener() {}},
    localStorage: {getItem: () => 'ja', setItem() {}},
    fetch: async () => { throw new Error('network must stay unused while signed out'); }
  });
  const mounted = window.AmiCorLanguageSurface.mount(doc, window.AmiCorLanguage);
  assert.equal(mounted.painted, 'ja');
  assert.equal(select.value, 'ja');
  assert.equal(notice.hidden, false);
  assert.match(notice.textContent, /未検証|검증|επαληθευ|не проверена|nicht geprüft/);
  assert.equal(fallback.textContent, window.AmiCorLanguageSurface.fallbackText);
  assert.equal(doc.documentElement.lang, 'ja');
  const pushed = await window.AmiCorLanguage.push('de');
  assert.equal(pushed.business_delivery_operational, false);
  assert.equal(pushed.operational, false);
  assert.equal(pushed.translation_verified, false);
  assert.equal(pushed.voice_interpretation, false);
  assert.equal(pushed.bidirectional_text, false);
  select.value = 'ko';
  await select.listeners.change();
  assert.equal(select.value, 'ko');
  assert.equal(notice.hidden, false);
});

test('authentication markup stays in place around the new control', () => {
  const today = read(pages.today);
  const studio = read(pages.studio);
  const sandbox = read(pages['casting-sandbox']);
  const snap = read(pages.snap);
  const preview = read(pages['casting-preview']);
  assert.match(today, /src="\/static\/ux\/sessionManager\.js"/);
  assert.ok(today.indexOf('sessionManager.js') < today.indexOf('nova-today/today.js'));
  assert.ok(today.indexOf('preference.js') < today.indexOf('nova-today/today.js'));
  assert.match(today, /id="login-form"/);
  assert.match(studio, /src="\/static\/nova-creative\/auth-session-guard\.js"/);
  assert.ok(studio.indexOf('auth-session-guard.js') < studio.indexOf('creative.js'));
  assert.match(studio, /id="login-email"/);
  assert.match(studio, /id="login-password"/);
  assert.match(sandbox, /id="login-form"/);
  assert.match(sandbox, /amicor_nova_creative_token/);
  assert.ok(sandbox.indexOf('surface.js') < sandbox.indexOf('<script>'));
  assert.match(snap, /id="login-form"/);
  assert.ok(snap.indexOf('sessionManager.js') < snap.indexOf('communications.js'));
  assert.doesNotMatch(preview, /fetch\(/);
  assert.doesNotMatch(preview, /localStorage/);
  assert.match(preview, /not a live audition portal/);
  assert.match(snap, /Nova Snap screen language/);
});
