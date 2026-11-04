const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

for (const view of ['nova-home', 'nova-today']) {
  test(view + ' signed-in buttons are mutually exclusive', () => {
    const js = read('backend/static/' + view + '/' + (view === 'nova-home' ? 'home.js' : 'today.js'));
    const html = read('backend/static/' + view + '/index.html');
    const method = js.match(/function setSignedIn\(on\)\s*\{([\s\S]*?)\n  \}/);
    assert.ok(method, 'setSignedIn missing');
    assert.match(method[1], /\$\("sign-in-toggle"\)\.classList\.toggle\("hidden", !!on\)/);
    assert.match(method[1], /\$\("sign-out"\)\.classList\.toggle\("hidden", !on\)/);
    assert.match(html, /id="login-password-toggle"/);
    assert.match(js, /field\.type = revealed \? "text" : "password"/);
    assert.match(js, /setAttribute\("aria-pressed", String\(revealed\)\)/);
  });
}

test('reset password visibility controls remain local to their fields', () => {
  const html = read('backend/static/nova-auth/reset.html');
  const js = read('backend/static/nova-auth/reset.js');
  for (const id of ['new_password', 'confirm_password']) {
    assert.match(html, new RegExp('id="' + id + '-toggle"'));
  }
  assert.match(js, /\["new_password", "confirm_password"\]\.forEach/);
  assert.match(js, /field\.type = revealed \? "text" : "password"/);
});

test('Nova Today keeps text answers visible and voice playback user-initiated', () => {
  const html = read('backend/static/nova-today/index.html');
  const js = read('backend/static/nova-today/today.js');
  assert.match(html, /id="read-answer"/);
  assert.match(js, /lastBrainAnswer = answer;/);
  assert.match(js, /\$\("read-answer"\)\.addEventListener\("click"/);
  assert.doesNotMatch(js, /speakNova\(answer\);/);
});
