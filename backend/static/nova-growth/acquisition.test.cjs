const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(__dirname + '/acquisition.js', 'utf8');

function setup() {
  class Element {
    constructor(tag = 'div') { this.tag = tag; this.children = []; this.listeners = {}; this.value = ''; }
    addEventListener(event, fn) { this.listeners[event] = fn; }
    append(...nodes) {
      this.children.push(...nodes);
      if (this.tag === 'select' && !this.value) this.value = nodes[0]?.value || '';
    }
    replaceChildren(...nodes) { this.children = []; this.value = ''; this.append(...nodes); }
    get options() { return this.children; }
    set innerHTML(_) { throw Error('HTML interpolation forbidden'); }
  }
  const elements = new Map();
  for (const id of ['load', 'status', 'plan', 'counts', 'review', 'contact', 'stage', 'open', 'permission', 'sending', 'sensitive', 'save']) {
    elements.set('acquisition-' + id, new Element(id === 'contact' || id === 'stage' ? 'select' : 'div'));
  }
  elements.set('sign-out', new Element()); elements.set('login-form', new Element());
  let session = 'owner-token';
  const calls = [];
  const pending = [];
  const context = {
    document: { getElementById: (id) => elements.get(id), createElement: (tag) => new Element(tag) },
    localStorage: { getItem: () => session }, window: { addEventListener() {} },
    fetch: (url, options) => { calls.push({ url, options }); return new Promise((resolve) => pending.push(resolve)); },
  };
  vm.runInNewContext(source, context);
  const $ = (id) => elements.get(id);
  const respond = (value) => pending.shift()({ ok: true, json: async () => value });
  const board = {
    plan: { name: 'Pilot', audience: 'Businesses', offer: 'Drafts', entry_offer: '$49 after scope', scope: 'Drafts only', hook: 'Hook', call_to_action: 'Scope check', channels: [] },
    counts: { new: 1 }, contacts: [{ id: 'lead-1', review: { stage: 'new' } }], total_reviewed: 1, unassigned_contacts: 0,
  };
  return { $, calls, respond, board, setToken: (value) => { session = value; } };
}

test('signed-out load makes no network request', async () => {
  const h = setup(); h.setToken('');
  await h.$('acquisition-load').listeners.click();
  assert.equal(h.calls.length, 0);
  assert.match(h.$('acquisition-status').textContent, /Sign in/);
});

test('sign-out discards late contact responses and clears the panel', async () => {
  const h = setup();
  const load = h.$('acquisition-load').listeners.click();
  h.setToken(''); h.$('sign-out').listeners.click();
  h.respond(h.board); h.respond({ leads: [{ id: 'lead-1', display_name: 'Private name' }] });
  await load;
  assert.equal(h.$('acquisition-contact').children.length, 0);
  assert.equal(h.$('acquisition-plan').children.length, 0);
  assert.equal(h.$('acquisition-review').hidden, true);
});

test('owner contact names render as text and synthetic records stay out', async () => {
  const h = setup();
  const load = h.$('acquisition-load').listeners.click();
  h.respond(h.board);
  h.respond({ leads: [{ id: 'lead-1', display_name: '<img onerror=alert(1)>' }, { id: 'demo', is_synthetic_demo: true }] });
  await load;
  assert.equal(h.$('acquisition-contact').children.length, 1);
  assert.equal(h.$('acquisition-contact').children[0].textContent, '<img onerror=alert(1)>');
  assert.match(h.$('acquisition-counts').textContent, /Payments not verified/);
  assert.equal(h.$('acquisition-review').hidden, false);
  h.$('login-form').listeners.submit();
  assert.equal(h.$('acquisition-contact').children.length, 0);
});
