const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = p => fs.readFileSync(path.join(__dirname, '../../backend/static', p), 'utf8');

function controlsHarness(adapter) {
  let observers = 0, extraEngines = 0, reads = [], stops = 0, controls;
  function element() {
    return { dataset: {}, children: [], handlers: {}, textContent: '', setAttribute() {},
      appendChild(x) { this.children.push(x); }, addEventListener(k, fn) { this.handlers[k] = fn; } };
  }
  const output = element(); output.textContent = 'Fixture answer';
  output.insertAdjacentElement = (where, node) => { controls = node; };
  const window = { location: {search: ''}, setTimeout() {}, clearTimeout() {},
    MutationObserver: class { constructor() { observers++; } observe() {} },
    AmiCorHumanVoice: { createEngine() { extraEngines++; return {speak() {}, stop() {}}; } } };
  if (adapter) window.NovaTodaySpeech = { speak(text) { reads.push(text); }, stop() { stops++; } };
  const document = { readyState: 'complete', documentElement: {getAttribute() {return 'en-US';}},
    querySelectorAll() {return [];}, querySelector() {return null;},
    getElementById(id) {return id === 'brain-output' ? output : null;}, createElement: element };
  vm.runInNewContext(read('ux/novaVoiceControls.js'), {window, document, URLSearchParams, MutationObserver: window.MutationObserver});
  return {window, output, controls, reads, observers: () => observers, extraEngines: () => extraEngines, stops: () => stops};
}

test('Today owns auto-read; manual Read aloud and Stop use the same reader', () => {
  const h = controlsHarness(true);
  assert.equal(h.observers(), 0, 'loading and answer DOM mutations must not create a second automatic reader');
  h.controls.children[0].handlers.click();
  assert.deepEqual(h.reads, ['Fixture answer']);
  h.controls.children[1].handlers.click();
  assert.equal(h.stops(), 1);
  assert.equal(h.extraEngines(), 0);
});

test('pages without a speech owner retain the shared auto-reader', () => {
  const h = controlsHarness(false);
  assert.equal(h.observers(), 1);
});

test('Today shows preparing, actual playback and failure separately without losing the answer', () => {
  const source = read('nova-today/today.js');
  let config;
  const elements = {'brain-output': {textContent: 'Fixture answer'}, 'voice-status': {textContent: ''}};
  const window = {AmiCorHumanVoice: {createEngine(options) {config = options; return {speak: async () => false, stop() {}};}}};
  vm.runInNewContext(source.slice(source.indexOf('  function setVoiceStatus('), source.indexOf('  function startVoiceInput(')),
    {window, $: id => elements[id]});
  window.NovaTodaySpeech.speak('Fixture answer');
  config.onState({preparing: true, reason: 'speak-start'});
  assert.match(elements['voice-status'].textContent, /Preparing/);
  config.onState({speaking: true, reason: 'audio-playing'});
  assert.equal(elements['voice-status'].textContent, 'Nova is speaking…');
  config.onState({speaking: false, reason: 'speak-failed'});
  assert.match(elements['voice-status'].textContent, /Tap Read aloud/);
  assert.equal(elements['brain-output'].textContent, 'Fixture answer');
});

test('Today explains when the browser has no audio support', () => {
  const source = read('nova-today/today.js');
  const status = {textContent: ''}, window = {};
  vm.runInNewContext(source.slice(source.indexOf('  function setVoiceStatus('), source.indexOf('  function startVoiceInput(')),
    {window, $: () => status});
  window.NovaTodaySpeech.speak('Fixture answer');
  assert.match(status.textContent, /Audio is unavailable.*ready to read/);
});

function engineHarness(blocked, transport) {
  const states = [];
  let audio;
  class Audio {
    constructor() {audio = this;}
    play() {return blocked ? Promise.reject(new Error('autoplay blocked')) : Promise.resolve();}
    pause() {}
  }
  const window = {};
  const fetch = transport || (async url => ({ok: true, json: async () => url.endsWith('/providers') ? {} : {audio_b64: 'AQ==', mime_type: 'audio/mpeg'}}));
  vm.runInNewContext(read('ux/humanVoiceEngine.js'), {
    window, fetch, Audio, Blob, atob, Uint8Array, AbortController,
    URL: {createObjectURL() {return 'blob:fixture';}, revokeObjectURL() {}},
    setTimeout(fn) {Promise.resolve().then(fn); return 1;}
  });
  return {states, audio: () => audio, engine: window.AmiCorHumanVoice.createEngine({onState: state => states.push(state)})};
}

test('voice does not claim playback until the audio playing event', async () => {
  const h = engineHarness(false);
  const pending = h.engine.speak('Fixture answer.');
  for (let i = 0; i < 20 && !h.audio(); i++) await Promise.resolve();
  assert.ok(h.audio());
  assert.ok(h.states.some(s => s.preparing));
  assert.equal(h.states.some(s => s.speaking), false);
  h.audio().onplaying();
  assert.equal(h.states[h.states.length - 1].reason, 'audio-playing');
  h.audio().onended();
  assert.equal(await pending, true);
  assert.equal(h.states[h.states.length - 1].reason, 'speak-complete');
});

test('blocked playback without a fallback reports failure rather than successful speech', async () => {
  const h = engineHarness(true);
  assert.equal(await h.engine.speak('Fixture answer.'), false);
  assert.equal(h.states.some(s => s.speaking), false);
  assert.equal(h.states[h.states.length - 1].reason, 'speak-failed');
});

test('Stop during synthesis prevents retry and browser fallback from restarting speech', async () => {
  let rejectAudio, synthesisCalls = 0;
  const h = engineHarness(false, async url => {
    if (url.endsWith('/providers')) return {ok: true, json: async () => ({})};
    synthesisCalls++;
    return new Promise((resolve, reject) => {rejectAudio = reject;});
  });
  const pending = h.engine.speak('Fixture answer.');
  for (let i = 0; i < 20 && !rejectAudio; i++) await Promise.resolve();
  assert.ok(rejectAudio);
  h.engine.stop('owner-stop');
  rejectAudio(new Error('aborted'));
  assert.equal(await pending, false);
  assert.equal(synthesisCalls, 1);
  assert.equal(h.states[h.states.length - 1].reason, 'owner-stop');
  assert.equal(h.states.some(s => s.speaking), false);
});
