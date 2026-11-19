'use strict';
// Real Chromium browser acceptance against an ephemeral loopback-only FastAPI server.
// Every account and inquiry is synthetic. No external providers or live Cloudflare.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const base = 'http://127.0.0.1:18765';
  const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto(base+'/nova/growth', {waitUntil:'domcontentloaded'});
    const load = page.locator('#website-inquiries-preview-load');
    const status = page.locator('#website-inquiries-preview-status');
    const list = page.locator('#website-inquiries-preview-list');
    await load.click();
    await assert.match(await status.textContent(), /Owner sign-in required/);
    assert.equal(await list.locator('div').count(),0);
    const anon = await page.request.get(base+'/api/nova/growth-agent/website-inquiries/preview');
    assert.ok([401,403].includes(anon.status()), 'unauthenticated preview must be forbidden');

    await page.locator('#login-email').fill('admin@amicor.local');
    await page.locator('#login-password').fill(process.env.CI_SYNTHETIC_OWNER_PASSWORD);
    await page.locator('#login-form button[type="submit"]').click();
    await page.waitForFunction(()=>!!localStorage.getItem('amicor_growth_token'));
    await load.click();
    await status.getByText('Synthetic example only', {exact:false}).waitFor({timeout:12000}).catch(async()=>{
      await page.waitForFunction(()=>document.querySelector('#website-inquiries-preview-status')?.textContent.includes('Synthetic example only'),null,{timeout:12000});
    });
    assert.equal(await list.locator('div').count(),1);
    assert.match(await list.textContent(), /Fictional Example Company/);
    assert.doesNotMatch(await list.textContent(), /live customer|actual revenue/i);
    // Actual owner dashboard connection control must report disconnected,
    // never claim there are zero customer inquiries.
    const connectionButton = page.locator('#website-inquiries-live-check');
    const connectionStatus = page.locator('#website-inquiries-live-status');
    const connectionList = page.locator('#website-inquiries-live-list');
    await connectionButton.click();
    await page.waitForFunction(() => document.querySelector('#website-inquiries-live-status')?.textContent.includes('Not connected.'), null, {timeout:12000});
    assert.match(await connectionStatus.textContent(), /does not mean zero customer requests/);
    assert.equal(await connectionList.locator('div').count(), 0);
    const token=await page.evaluate(()=>localStorage.getItem('amicor_growth_token'));
    const cross=await page.request.get(base+'/api/nova/growth-agent/website-inquiries/preview?organization_id=foreign-tenant',{headers:{Authorization:'Bearer '+token}});
    assert.equal(cross.status(),403);

    await page.locator('#sign-out').click();
    await page.waitForFunction(()=>document.querySelector('#website-inquiries-live-status')?.textContent.includes('Sign in before checking.'));
    assert.equal(await connectionList.locator('div').count(), 0);
    await page.waitForFunction(()=>!localStorage.getItem('amicor_growth_token'));
    assert.equal(await list.locator('div').count(),0);
    await load.click();
    assert.match(await status.textContent(),/Owner sign-in required/);
    assert.equal(await list.locator('div').count(),0);
    assert.deepEqual(errors,[]);
    console.log('PASS: Chromium owner login, synthetic preview, disconnected source status, cross-tenant denial, sign-out, anonymous denial');
  } finally {
    await page.screenshot({path:'pr521-browser-evidence.png',fullPage:true}).catch(()=>{});
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
