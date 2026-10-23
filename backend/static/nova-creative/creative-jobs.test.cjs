const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/creative.js', 'utf8');
const polling = source.slice(source.indexOf('  async function waitForScene('), source.indexOf('  async function waitForFinalPromo('));

test('saved motion failures render the provider reason safely after a project reload', async () => {
  const elements = {'asset-list': {innerHTML: ''}};
  const ctx = vm.createContext({
    activeProjectId: 'selected',
    $: id => elements[id],
    api: async () => ({assets: [
      {title: 'Scene 1', kind: 'video', status: 'ERROR', content: 'Hotel lobby', metadata: {provider_result: {message: 'Runway error 400: insufficient credits <script>alert(1)</script> Bearer secret-token'}}},
      {title: 'Dialogue', kind: 'audio', status: 'GENERATED', url: '/voice.mp3'},
    ]}),
    refreshDrama: () => {}, renderProductionReadiness: () => {},
    document: {querySelectorAll: () => []},
  });
  const escape = source.slice(source.indexOf('  function escapeHtml('), source.indexOf('  function loadImage('));
  const memoryNotice = source.slice(source.indexOf('  function memoryHeadroomNotice('), source.indexOf('  function assetFailureHtml('));
  const failure = source.slice(source.indexOf('  function assetFailureHtml('), source.indexOf('  async function downloadBrandedImage('));
  const refresh = source.slice(source.indexOf('  function assetTypeLabel('), source.indexOf('  async function waitForScene('));
  // refreshAssets is followed by event registration; isolate its declaration.
  const end = refresh.indexOf('\n  $("reset-project-media")');
  vm.runInContext(escape + memoryNotice + failure + (end >= 0 ? refresh.slice(0, end) : refresh), ctx);
  await ctx.refreshAssets();
  const html = elements['asset-list'].innerHTML;
  assert.match(html, /insufficient credits/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>|secret-token/);
  assert.match(html, /Download voice/);
});

function context(responses) {
  const calls = [];
  const ctx = vm.createContext({
    activeProjectId: 'selected',
    setTimeout: (cb) => cb(),
    api: async (path) => { calls.push(path); const response = responses.shift(); if (response instanceof Error) throw response; return response; },
    showBanner: () => {}, refreshAssets: async () => {},
  });
  vm.runInContext(polling, ctx);
  return {ctx, calls};
}

test('polling ignores an older job and returns the asset of the requested job', async () => {
  const {ctx, calls} = context([
    {jobs: [{id: 'old', status: 'GENERATED'}, {id: 'new', status: 'RUNNING'}]},
    {jobs: [{id: 'new', status: 'GENERATED', result_asset_ids: ['scene2']}], assets: [{id: 'scene1', url: 'old.mp4'}, {id: 'scene2', url: 'new.mp4', metadata: {provider_result: {status: 'GENERATED'}}}]},
  ]);
  const result = await ctx.waitForScene('selected', 'new');
  assert.equal(result.url, 'new.mp4');
  assert.equal(result.provider.status, 'GENERATED');
  assert.equal(calls.length, 2);
  assert.ok(calls.every(path => path.endsWith('/selected')));
});

test('worker errors surface their reason instead of a success banner', async () => {
  const {ctx} = context([{jobs: [{id: 'new', status: 'ERROR', message: 'Runway credits unavailable'}]}]);
  await assert.rejects(ctx.waitForScene('selected', 'new'), /Runway credits unavailable/);
});

test('project switching does not change the job being polled', async () => {
  const {ctx, calls} = context([{jobs: [{id: 'new', status: 'GENERATED', result_asset_ids: []}]}]);
  ctx.activeProjectId = 'other-project';
  await ctx.waitForScene('original-project', 'new');
  assert.equal(calls[0], '/api/nova/creative/projects/original-project');
  assert.equal(ctx.activeProjectId, 'other-project');
});

function transientError(status) {
  return Object.assign(new Error('Temporary system error. (' + status + ')'), {status, retryable: true});
}

test('a gateway failure reconnects to the same job and retrieves its completed clip', async () => {
  const {ctx, calls} = context([
    transientError(502),
    {jobs: [{id: 'new', status: 'RUNNING'}]},
    transientError(503),
    {jobs: [{id: 'new', status: 'GENERATED', result_asset_ids: ['clip']}], assets: [{id: 'clip', url: 'done.mp4'}]},
  ]);
  ctx.refreshAssets = async () => { throw new Error('redundant fetch must not interrupt polling'); };
  const result = await ctx.waitForScene('selected', 'new');
  assert.equal(result.url, 'done.mp4');
  assert.equal(calls.length, 4);
  assert.ok(calls.every(path => path === '/api/nova/creative/projects/selected'));
});

test('persistent connection failures report unknown job state, not generation failure', async () => {
  const {ctx, calls} = context(Array.from({length: 12}, () => transientError(502)));
  await assert.rejects(ctx.waitForScene('selected', 'new'), /job new.*result is unknown/);
  assert.equal(calls.length, 12);
});

test('session expiry is surfaced immediately without retries', async () => {
  const {ctx, calls} = context([new Error('Session expired. Sign in again. (401)')]);
  await assert.rejects(ctx.waitForScene('selected', 'new'), /Session expired/);
  assert.equal(calls.length, 1);
});

test('HTTP API marks gateway and network failures retryable but preserves session errors', async () => {
  const apiSource = source.slice(source.indexOf('  async function api('), source.indexOf('  function setSignedIn('));
  const ctx = vm.createContext({token: () => null, detailText: (_body, fallback) => fallback});
  vm.runInContext(apiSource, ctx);
  ctx.fetch = async () => ({status: 502, ok: false, json: async () => null});
  await assert.rejects(ctx.api('/status'), err => err.status === 502 && err.retryable === true);
  ctx.fetch = async () => { throw new Error('connection reset'); };
  await assert.rejects(ctx.api('/status'), err => err.retryable === true);
  ctx.fetch = async () => ({status: 401, ok: false, json: async () => null});
  await assert.rejects(ctx.api('/status'), err => !err.retryable && /401/.test(err.message));
});


test('sign-in uses one unauthenticated request and surfaces the login error without clearing the project session', async () => {
  const apiSource = source.slice(source.indexOf('  async function api('), source.indexOf('  function setSignedIn('));
  const calls = [];
  const ctx = vm.createContext({
    window: {AmiCorSession: {ensureReady: async () => { throw new Error('login must not refresh the old session'); }, authFetch: async () => { throw new Error('login must not replay through authFetch'); }}},
    token: () => 'old-token',
    detailText: body => body.detail,
    setToken: () => { throw new Error('login rejection must not clear the existing session'); },
    setSignedIn: () => { throw new Error('login rejection is not session expiry'); },
    fetch: async (path, options) => { calls.push({path, options}); return {status:401, ok:false, json:async () => ({detail:'Invalid email or password'})}; },
  });
  vm.runInContext(apiSource, ctx);
  await assert.rejects(ctx.api('/api/auth/login', {method:'POST',body:'test credentials fixture'}), /Sign-in failed.*Invalid email or password/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.headers.Authorization, undefined);
});

function response({status, contentType, disposition, bytes, jsonBody}) {
  const ok = status >= 200 && status < 300;
  return {
    status,
    ok,
    headers: {get: (name) => {
      const key = String(name || "").toLowerCase();
      if (key === "content-type") return contentType || "";
      if (key === "content-disposition") return disposition || "";
      return "";
    }},
    blob: async () => new Blob([bytes || new Uint8Array()], {type: (contentType || "application/octet-stream").split(";")[0]}),
    json: async () => jsonBody || {},
  };
}

test('asset download sends the current bearer, keeps the token out of the URL, and revokes the blob', async () => {
  const helper = source.slice(source.indexOf('  function assertDownloadUrlHasNoToken('), source.indexOf('  async function downloadBrandedImage('));
  const calls = [];
  let current = "owner-token";
  let created = 0;
  let revoked = 0;
  let signedIn = true;
  const link = {click() { link.clicked = true; }, remove() { link.removed = true; }};
  const ctx = vm.createContext({
    token: () => current,
    setToken: (value) => { current = value || ""; },
    setSignedIn: (on) => { signedIn = !!on; },
    session: () => null,
    fetch: async (url, options) => { calls.push({url, options}); return response({
      status: 200,
      contentType: "video/mp4",
      disposition: 'attachment; filename="nova-offline-montage.mp4"',
      bytes: Buffer.from("ftyp-playable"),
    }); },
    URL: {
      createObjectURL: () => { created += 1; return "blob:nova-mp4"; },
      revokeObjectURL: (url) => { revoked += 1; assert.equal(url, "blob:nova-mp4"); },
    },
    document: {
      createElement: () => link,
      body: {appendChild(node) { node.parentNode = true; }},
    },
    setTimeout: (fn) => { fn(); },
    Blob,
  });
  vm.runInContext(helper, ctx);
  const fileUrl = "/api/nova/creative/projects/cproj_293e7b8547d4/assets/asset-1/file";
  const saved = await ctx.downloadProtectedAsset(fileUrl, "fallback.mp4");
  assert.equal(saved.fileName, "nova-offline-montage.mp4");
  assert.equal(saved.mime, "video/mp4");
  assert.equal(calls[0].url, fileUrl);
  assert.equal(calls[0].options.headers.Authorization, "Bearer owner-token");
  assert.equal(calls[0].url.includes("token="), false);
  assert.equal(link.download, "nova-offline-montage.mp4");
  assert.equal(created, 1);
  assert.equal(revoked, 1);
  assert.equal(signedIn, true);

  current = "refreshed-token";
  calls.length = 0;
  await ctx.downloadProtectedAsset(fileUrl + "?part=captions", "nova-captions.srt");
  assert.equal(calls[0].options.headers.Authorization, "Bearer refreshed-token");
  assert.equal(calls[0].url.endsWith("?part=captions"), true);
  assert.equal(calls[0].url.includes("access_token"), false);
});

test('a revoked session and a JSON error do not save file.json', async () => {
  const helper = source.slice(source.indexOf('  function assertDownloadUrlHasNoToken('), source.indexOf('  async function downloadBrandedImage('));
  const calls = [];
  let current = "revoked-token";
  let created = 0;
  const ctx = vm.createContext({
    token: () => current,
    setToken: (value) => { current = value || ""; },
    setSignedIn: () => {},
    session: () => ({clear() { ctx.cleared = true; }}),
    fetch: async (url, options) => {
      calls.push({url, authorization: options.headers.Authorization});
      if (calls.length === 1) return response({status: 401, contentType: "application/json", jsonBody: {detail: "Authentication required"}});
      if (String(url).includes("forbidden")) return response({status: 403, contentType: "application/json", jsonBody: {detail: "Access denied"}});
      return response({status: 404, contentType: "application/json", jsonBody: {detail: "Asset not found"}});
    },
    URL: {createObjectURL: () => { created += 1; return "blob:should-not"; }, revokeObjectURL: () => {}},
    document: {createElement: () => { throw new Error("no anchor for an error"); }, body: {appendChild() {}}},
    setTimeout: (fn) => fn(),
    Blob,
  });
  vm.runInContext(helper, ctx);
  await assert.rejects(ctx.downloadProtectedAsset("/api/nova/creative/projects/p/assets/a/file", "x.mp4"), /Session expired/);
  assert.equal(current, "");
  assert.equal(ctx.cleared, true);
  assert.equal(created, 0);
  current = "other-tenant";
  await assert.rejects(ctx.downloadProtectedAsset("/api/nova/creative/projects/p/assets/a/file?forbidden=1", "x.mp4"), /403/);
  await assert.rejects(ctx.downloadProtectedAsset("/api/nova/creative/projects/p/assets/a/file", "x.mp4"), /404/);
  await assert.rejects(
    ctx.downloadProtectedAsset("/api/nova/creative/projects/p/assets/a/file?access_token=secret", "x.mp4"),
    /Refusing to put an access token/
  );
  assert.equal(calls.some(call => String(call.url).includes("access_token")), false);
});

test('offline montage readiness stays preview-only and does not false-green the click URL', async () => {
  const helpers = source.slice(source.indexOf('  function presenterMarkedPublishReady('), source.indexOf('  function memoryHeadroomNotice('))
    + source.slice(source.indexOf('  function clickVerified('), source.indexOf('  function assetFailureHtml('))
    + source.slice(source.indexOf('  function latestAsset('), source.indexOf('  var dramaLoadedProject'));
  const elements = {"production-readiness": {innerHTML: "", querySelectorAll: () => []}};
  const ctx = vm.createContext({
    $: (id) => elements[id],
    activeProjectId: "cproj_293e7b8547d4",
    escapeHtml: (value) => String(value == null ? "" : value),
    document: {querySelectorAll: () => []},
    showBanner: () => {},
    api: async () => ({}),
  });
  vm.runInContext(helpers, ctx);
  await ctx.renderProductionReadiness({
    project: {project_type: "short_video", platform: "TikTok"},
    brand: null,
    assets: [{
      id: "vid",
      kind: "video",
      status: "GENERATED",
      url: "/media/offline.mp4",
      metadata: {
        final_promo: true,
        render_mode: "offline_montage_not_lipsync",
        pipeline: "offline_title_card_fallback",
        quality_state: "PREVIEW_ONLY",
        presenter_used: false,
        presenter: false,
        lip_sync: false,
        commercial_complete: true,
        license_status: "AMBER",
        narration: {engine: "espeak-ng", license: "GPL-3.0-or-later"},
        click_destination: {
          website_field_url: "https://getamicor.com/nova-today/?utm_source=tiktok&utm_medium=profile_website&utm_campaign=nova_30s_commercial",
          classification: "first_party_nova",
          verified: true,
        },
      },
    }],
  });
  const html = elements["production-readiness"].innerHTML;
  assert.match(html, /NEEDS WORK/);
  assert.match(html, /PREVIEW_ONLY title cards/);
  assert.match(html, /NOT USED/);
  assert.match(html, /not yet verified/);
  assert.match(html, /Select or save brand/);
  assert.doesNotMatch(html, /COMMERCIAL COMPLETE/);

  await ctx.renderProductionReadiness({
    project: {project_type: "short_video"},
    brand: {id: "brand-1", business_name: "AMICOR Nova"},
    assets: [{
      id: "vid",
      kind: "video",
      status: "GENERATED",
      url: "/media/offline.mp4",
      metadata: {
        final_promo: true,
        render_mode: "offline_montage_not_lipsync",
        quality_state: "PREVIEW_ONLY",
        presenter_used: false,
        click_destination: {
          website_field_url: "https://www.tiktok.com/",
          classification: "platform_home",
          verified: true,
          http_status: 200,
        },
      },
    }],
  });
  const diverted = elements["production-readiness"].innerHTML;
  function item(html, label) {
    const marker = "<strong>" + label + "</strong>";
    const at = html.indexOf(marker);
    assert.notEqual(at, -1, label);
    return html.slice(Math.max(0, at - 220), at);
  }
  assert.match(item(diverted, "Brand profile"), /readiness-item ready/);
  assert.match(item(diverted, "Nova click destination"), /readiness-item missing/);
  assert.match(item(html, "Commercial complete"), /readiness-item missing/);
  assert.match(item(html, "Nova click destination"), /readiness-item missing/);
  assert.match(item(html, "Brand profile"), /readiness-item missing/);
});

test('offline asset markup downloads through a button and never puts the file API in an href', async () => {
  const escape = source.slice(source.indexOf('  function escapeHtml('), source.indexOf('  function loadImage('));
  const memoryNotice = source.slice(source.indexOf('  function memoryHeadroomNotice('), source.indexOf('  function clickVerified('));
  const failure = source.slice(source.indexOf('  function assetFailureHtml('), source.indexOf('  function assertDownloadUrlHasNoToken('));
  const labels = source.slice(source.indexOf('  function assetTypeLabel('), source.indexOf('  async function waitForScene('));
  const end = labels.indexOf('\n  var clearLegacyPreviews');
  assert.ok(end > 0, "refreshAssets slice marker missing");
  const elements = {"asset-list": {innerHTML: ""}};
  const ctx = vm.createContext({
    activeProjectId: "cproj_293e7b8547d4",
    $: (id) => elements[id],
    refreshDrama: () => {},
    renderProductionReadiness: () => {},
    document: {querySelectorAll: () => []},
    api: async () => ({
      project: {title: "Validation", metadata: {production_settings: {}}},
      assets: [{
        id: "asset-1",
        title: "Offline 30s",
        kind: "video",
        status: "GENERATED",
        url: "/media/nova-creative/offline.mp4",
        content: "title cards",
        metadata: {
          render_mode: "offline_montage_not_lipsync",
          pipeline: "offline_title_card_fallback",
          quality_state: "PREVIEW_ONLY",
          presenter_used: false,
          license_status: "AMBER",
          subtitle_url: "/media/nova-creative/offline.srt",
          narration: {commercial_use: "GPL review only"},
        },
      }],
    }),
  });
  vm.runInContext(escape + memoryNotice + failure + labels.slice(0, end), ctx);
  await ctx.refreshAssets();
  const html = elements["asset-list"].innerHTML;
  assert.match(html, /asset-auth-download/);
  assert.match(html, /Download offline montage/);
  assert.match(html, /Download captions/);
  assert.match(html, /part=captions/);
  assert.match(html, /PREVIEW_ONLY/);
  assert.match(html, /Presenter NOT USED/);
  assert.doesNotMatch(html, /href="\/api\/nova\/creative\/[^"]+\/file/);
  assert.doesNotMatch(html, /access_token|Bearer /);
});
