const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/nova-home/home.js'), 'utf8');
function node(tag = '#text', text = '') {
  return {tag, children:[], _text:text,
    set textContent(v) {this._text = v; this.children = [];},
    get textContent() {return this._text + this.children.map(c => c.textContent).join('');},
    appendChild(child) {this.children.push(child);}
  };
}
function render(result) {
  const box = node('pre');
  const c = vm.createContext({$: () => box, document:{createElement:node,createTextNode:t=>node('#text',t)}});
  vm.runInContext(source.slice(source.indexOf('  function renderBrainResult('),source.indexOf('  async function askBrain(')),c);
  c.renderBrainResult(result);
  return box;
}
test('Home shows every official source as a clickable link without changing the answer', () => {
  const urls = ['https://sam.gov/entity-registration','https://www.sba.gov/certifications/','https://www.acquisition.gov/far/32.905'];
  const box = render({fact_label:'LIVE WEB SOURCES',answer:'Fixture answer [1] [2] [3]',sources:urls.map((url,i)=>({url,title:'Official source '+(i+1)}))});
  assert.match(box.textContent,/Fixture answer \[1\] \[2\] \[3\]/);
  assert.deepEqual(box.children.filter(c=>c.tag==='a').map(c=>c.href),urls);
  for(const link of box.children.filter(c=>c.tag==='a')) {
    assert.equal(link.target,'_blank'); assert.equal(link.rel,'noopener noreferrer');
  }
});
test('Home keeps untrusted titles and answers as text and rejects executable links', () => {
  const box=render({answer:'<script>fixture</script>',sources:[{url:'javascript:alert(1)',title:'Unsafe'},{url:'https://sam.gov/',title:'<img src=x onerror=fixture>'}]});
  assert.equal(box.children.filter(c=>c.tag==='a').length,1);
  assert.match(box.textContent,/<script>fixture<\/script>/);
  assert.match(box.textContent,/<img src=x onerror=fixture>/);
});
test('Home retains legacy source references and handles an external fallback URL', () => {
  const box=render({answer:'Saved record fixture',source_href:'/nova/government'});
  assert.match(box.textContent,/Source: \/nova\/government/);
  assert.equal(box.children.some(c=>c.tag==='a'),false);
  const external=render({answer:'Fixture',source_href:'https://sam.gov/'});
  assert.equal(external.children.filter(c=>c.tag==='a').length,1);
});
