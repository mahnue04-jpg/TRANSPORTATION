const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../backend/static/nova-today/today.js'), 'utf8');
function node(tag = '#text', text = '') {
  return { tag, children: [], _text: text,
    set textContent(v) { this._text = v; this.children = []; },
    get textContent() { return this._text + this.children.map(c => c.textContent).join(''); },
    appendChild(child) { this.children.push(child); }
  };
}
function render(result) {
  const box = node('pre');
  const context = vm.createContext({ $: () => box, document: { createElement: node, createTextNode: text => node('#text', text) } });
  vm.runInContext(source.slice(source.indexOf('  function renderBrainAnswer('), source.indexOf('  var brainBusy =')), context);
  context.renderBrainAnswer(result);
  return box;
}
test('cited text has a visible safe inline source link', () => {
  const box = render({ fact_label: 'LIVE WEB SOURCES', answer: 'Fixture [1]', answer_parts: [{ text: 'Fixture ' }, { text: '[1]', url: 'https://www.nba.com/fixture', title: 'NBA fixture' }] });
  assert.equal(box.textContent, 'LIVE WEB SOURCES\n\nFixture [1]');
  const link = box.children.find(c => c.tag === 'a');
  assert.equal(link.href, 'https://www.nba.com/fixture');
  assert.equal(link.rel, 'noopener noreferrer');
});
test('unsafe citation schemes stay literal text', () => {
  const box = render({ answer: '<script>x</script> [1]', answer_parts: [{ text: '<script>x</script> ' }, { text: '[1]', url: 'javascript:alert(1)' }] });
  assert.equal(box.children.some(c => c.tag === 'a'), false);
  assert.match(box.textContent, /<script>x<\/script>/);
});
test('mismatched segments cannot replace the actual answer', () => {
  const box = render({ answer: 'Actual answer', answer_parts: [{ text: 'Different answer', url: 'https://example.com' }] });
  assert.match(box.textContent, /Actual answer/);
  assert.equal(box.children.some(c => c.tag === 'a'), false);
});
