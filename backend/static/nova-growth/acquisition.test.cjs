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
  for (const id of ['load', 'status', 'plan', 'counts', 'review', 'contact', 'stage', 'open', 'permission', 'sending', 'sensitive', 'save', 'feedback']) {
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
  const respond = (value, ok = true) => pending.shift()({ ok, json: async () => value });
  const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
  const board = {
    plan: { name: 'Pilot', audience: 'Businesses', offer: 'Drafts', entry_offer: '$49 after scope', scope: 'Drafts only', hook: 'Hook', call_to_action: 'Scope check', channels: [] },
    counts: { new: 1 }, contacts: [{ id: 'lead-1', review: { stage: 'new' } }], total_reviewed: 1, unassigned_contacts: 0,
  };
  return { $, calls, respond, flush, board, setToken: (value) => { session = value; } };
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


test('saving a second contact preserves selection and confirms the saved review', async () => {
  const h = setup();
  const leadRows = { leads: [
    { id: 'lead-1', display_name: 'First' },
    { id: 'lead-2', display_name: 'Second' },
  ] };
  const board = { ...h.board, contacts: [
    { id: 'lead-1', review: { stage: 'new' } },
    { id: 'lead-2', review: { stage: 'qualified', has_open_inquiries: true, authorized_list_use: true } },
  ] };
  const firstLoad = h.$('acquisition-load').listeners.click();
  h.respond(board); h.respond(leadRows);
  await firstLoad;
  h.$('acquisition-contact').value = 'lead-2';
  h.$('acquisition-contact').listeners.change();
  assert.equal(h.$('acquisition-stage').value, 'qualified');
  const saving = h.$('acquisition-review').listeners.submit({ preventDefault() {} });
  assert.match(h.calls.at(-1).url, /contacts\/lead-2\/review$/);
  h.respond({ changed: true });
  await h.flush();
  assert.equal(h.calls.length, 5, 'save must queue two refreshed GET requests');
  // The server returns an updated board for the same selected contact.
  h.respond(board); h.respond(leadRows);
  await saving;
  assert.equal(h.$('acquisition-contact').value, 'lead-2');
  assert.equal(h.$('acquisition-stage').value, 'qualified');
  assert.match(h.$('acquisition-feedback').textContent, /saved for the selected contact/i);
});

test('scope validation feedback is adjacent to Save and names each blocker', async () => {
  const h = setup();
  const loading = h.$('acquisition-load').listeners.click();
  h.respond(h.board); h.respond({ leads: [{ id: 'lead-1', display_name: 'First' }] });
  await loading;
  const saving = h.$('acquisition-review').listeners.submit({ preventDefault() {} });
  h.respond({ detail: { message: 'Review needs changes', details: {
    blockers: ['No open inquiries confirmed', 'List authorization is not confirmed']
  } } }, false);
  await saving;
  assert.match(h.$('acquisition-feedback').textContent, /No open inquiries confirmed/);
  assert.match(h.$('acquisition-feedback').textContent, /List authorization is not confirmed/);
  assert.equal(h.$('acquisition-feedback').className, 'error');
});

test('review checkboxes have explicit paired layout and feedback live region', () => {
  const html = fs.readFileSync(__dirname + '/index.html', 'utf8');
  const css = fs.readFileSync(__dirname + '/growth.css', 'utf8');
  for (const id of ['open', 'permission', 'sending', 'sensitive']) {
    assert.match(html, new RegExp('class="acquisition-check"[^>]*><input[^>]*id="acquisition-' + id + '"'));
  }
  assert.match(html, /id="acquisition-feedback"[^>]*role="status"[^>]*aria-live="polite"/);
  assert.match(css, /#acquisition-review \.acquisition-check\s*\{\s*flex-direction: row/);
});
