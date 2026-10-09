const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

for (const page of ['workspace', 'business']) {
  test(page + ' displays discovery provenance and safe source links after Ask Nova', async () => {
    const source = fs.readFileSync(__dirname + '/../nova-' + page + '/' + page + '.js', 'utf8');
    const handler = source.slice(source.indexOf('  async function runBrain('), source.indexOf('\n  if (session()'));
    const elements = new Map();
    const element = () => ({textContent: '', value: 'Find jobs', children: [], setAttribute() {}, appendChild(child) {this.children.push(child);}, classList: {remove() {}}});
    const ctx = vm.createContext({
      $: id => {if (!elements.has(id)) elements.set(id, element()); return elements.get(id);},
      state: {}, brainBusy: false, language: () => 'en', token: () => 'test', showBanner: () => {}, refresh: async () => {},
      api: async () => ({answer: 'One result ready for review.', fact_label: 'VERIFIED DATA', source_href: '/nova/work', sources: [{title: 'Buyer request', url: 'https://example.com/request'}, {title: 'Unsafe', url: 'javascript:alert(1)'}]}),
      document: {createElement: tag => ({tag}), querySelectorAll: () => []},
    });
    vm.runInContext(handler, ctx);
    await ctx.runBrain('ask');
    const output = elements.get('brain-output');
    assert.match(output.textContent, /VERIFIED DATA.*\n\nOne result/s);
    const links = output.children.filter(child => child.tag === 'a');
    assert.equal(links.length, 2);
    assert.equal(links[0].href, 'https://example.com/request');
    assert.equal(links[0].textContent, 'Buyer request');
    assert.equal(links[1].href, '/nova/work');
    assert.equal(links[0].rel, 'noopener noreferrer');
  });
}
