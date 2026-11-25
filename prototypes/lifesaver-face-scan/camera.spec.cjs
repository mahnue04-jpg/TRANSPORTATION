// Run: node --test prototypes/lifesaver-face-scan/camera.spec.cjs
// Playwright Chromium must be installed. Tests use a fake camera, not a physical phone.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

const target = pathToFileURL(path.resolve(__dirname, 'index.html')).href;

async function setup(cameraMode = 'allowed') {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.addInitScript(mode => {
    window.__camera = { calls: 0, stopped: 0 };
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => {
          window.__camera.calls++;
          if (mode === 'denied') {
            throw Object.assign(new Error('Permission denied'), { name: 'NotAllowedError' });
          }
          const track = {
            stop() { window.__camera.stopped++; },
            addEventListener() {}
          };
          return { getTracks: () => [track], getVideoTracks: () => [track] };
        }
      }
    });
    HTMLMediaElement.prototype.play = async function() {};
  }, cameraMode);
  await page.goto(target);
  return { browser, page };
}

test('camera cannot start without consent', async () => {
  const { browser, page } = await setup();
  try {
    assert.equal(await page.locator('#start').isDisabled(), true);
    assert.equal(await page.evaluate(() => window.__camera.calls), 0);
  } finally { await browser.close(); }
});

test('consent, start, and stop release camera tracks', async () => {
  const { browser, page } = await setup();
  try {
    await page.locator('#consent').check();
    await page.locator('#start').click();
    await page.getByText('Camera on. No vital signs are being measured.').waitFor();
    assert.equal(await page.evaluate(() => window.__camera.calls), 1);
    await page.locator('#stop').click();
    assert.equal(await page.evaluate(() => window.__camera.stopped), 1);
    assert.equal(await page.evaluate(() => document.querySelector('#preview').srcObject === null), true);
    assert.equal(await page.locator('#stop').isDisabled(), true);
  } finally { await browser.close(); }
});

test('withdrawing consent releases camera and prevents restarting', async () => {
  const { browser, page } = await setup();
  try {
    await page.locator('#consent').check();
    await page.locator('#start').click();
    await page.getByText('Camera on. No vital signs are being measured.').waitFor();
    await page.locator('#consent').uncheck();
    assert.equal(await page.evaluate(() => window.__camera.stopped), 1);
    assert.equal(await page.locator('#start').isDisabled(), true);
  } finally { await browser.close(); }
});

test('permission denial is visible and does not falsely start camera', async () => {
  const { browser, page } = await setup('denied');
  try {
    await page.locator('#consent').check();
    await page.locator('#start').click();
    await page.getByText('Camera unavailable: permission was denied.').waitFor();
    assert.equal(await page.locator('#stop').isDisabled(), true);
    assert.equal(await page.evaluate(() => window.__camera.stopped), 0);
  } finally { await browser.close(); }
});

test('pagehide releases camera tracks', async () => {
  const { browser, page } = await setup();
  try {
    await page.locator('#consent').check();
    await page.locator('#start').click();
    await page.getByText('Camera on. No vital signs are being measured.').waitFor();
    await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
    assert.equal(await page.evaluate(() => window.__camera.stopped), 1);
  } finally { await browser.close(); }
});

test('repeat start after stop does not reuse old camera', async () => {
  const { browser, page } = await setup();
  try {
    await page.locator('#consent').check();
    for (let n = 1; n <= 2; n++) {
      await page.locator('#start').click();
      await page.getByText('Camera on. No vital signs are being measured.').waitFor();
      await page.locator('#stop').click();
      assert.equal(await page.evaluate(() => window.__camera.stopped), n);
    }
    assert.equal(await page.evaluate(() => window.__camera.calls), 2);
  } finally { await browser.close(); }
});
