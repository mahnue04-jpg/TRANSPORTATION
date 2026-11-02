const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const root = path.join(__dirname, '../..');
const browser = process.env.CHROME_BIN || '/usr/bin/google-chrome';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'nova-auth-render-'));
try {
  for (const pageName of ['nova-home', 'nova-today', 'nova-government']) {
    for (const signedIn of [false, true]) {
      const dir = path.join(root, 'backend/static', pageName);
      let html = fs.readFileSync(path.join(dir, 'index.html'), 'utf8')
        .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
        .replace(/<link\b[^>]*>/gi, '');
      const css = fs.readFileSync(path.join(dir, pageName.replace('nova-', '') + '.css'), 'utf8');
      const source = fs.readFileSync(path.join(dir, pageName.replace('nova-', '') + '.js'), 'utf8');
      const fixture = `
        window.AmiCorSession = {
          restore() {}, getAccessToken() { return ${signedIn} ? 'offline-fixture' : ''; },
          getCurrent() { return {identity:{name:'Offline fixture'}}; },
          getAuthHeaders() { return {}; }, getOrganizationId() { return null; }
        };
        window.fetch = async () => ({ok:true,status:200,json:async()=>({})});
      `;
      const check = `
        setTimeout(() => {
          const visible = id => {const e=document.getElementById(id);return !!e && getComputedStyle(e).display !== 'none';};
          const failures = [];
          if(visible('sign-in-toggle') !== ${!signedIn}) failures.push('Sign in visibility');
          if(visible('sign-out') !== ${signedIn}) failures.push('Sign out visibility');
          if(visible('login-form')) failures.push('login form visible');
          if('${pageName}' === 'nova-home' && visible('create-nova-account') !== ${!signedIn}) failures.push('signup visibility');
          const compact=document.getElementById('compact-toggle');
          if(compact) {compact.click();if(visible('sign-in-toggle') !== ${!signedIn} || visible('sign-out') !== ${signedIn}) failures.push('compact visibility');}
          const out=document.createElement('output');out.id='auth-render-result';
          out.setAttribute('data-result',failures.length?'fail':'pass');
          out.textContent=failures.join(', ') || 'Rendered controls correct';
          document.body.appendChild(out);
        }, 50);
      `;
      html = html.replace('</head>', '<style>' + css + '</style></head>')
        .replace('</body>', '<script>' + fixture + '</script><script>' + source + '</script><script>' + check + '</script></body>');
      const file = path.join(tmp, pageName + '-' + signedIn + '.html');
      fs.writeFileSync(file, html);
      const dom = execFileSync(browser, ['--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
        '--no-first-run','--virtual-time-budget=1500','--dump-dom','file://' + file + (signedIn ? '?signin=1' : '')],
        {encoding:'utf8',timeout:20000,stdio:['ignore','pipe','pipe']});
      assert.match(dom, /<output id="auth-render-result" data-result="pass">/, pageName + ' signedIn=' + signedIn);
      console.log('PASS rendered ' + pageName + ' signedIn=' + signedIn);
    }
  }
} finally { fs.rmSync(tmp, {recursive:true,force:true}); }
