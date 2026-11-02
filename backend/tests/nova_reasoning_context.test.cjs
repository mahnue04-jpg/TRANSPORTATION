const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

for (const [page, file] of [['nova-home', 'home.js'], ['nova-today', 'today.js']]) {
  const source = fs.readFileSync(path.join(__dirname, '../static', page, file), 'utf8');
  function harness() {
    let access = 'fixture-account-a', org = 'fixture-org-a';
    const context = vm.createContext({token: () => access, session: () => ({getOrganizationId: () => org})});
    vm.runInContext(source.slice(source.indexOf('  // One successful turn'), source.indexOf('  function identity(')), context);
    return {context, account(value) {access = value;}, organization(value) {org = value;}};
  }
  test(`${page}: retains one bounded reasoning turn only in memory`, () => {
    const {context: c} = harness();
    c.rememberBrainTurn('a'.repeat(5000), {answer:'b'.repeat(9000),fact_label:'AI SUGGESTION'}, c.brainScope());
    assert.equal(c.previousBrainTurn().question.length, 4000);
    assert.equal(c.previousBrainTurn().answer.length, 8000);
    c.rememberBrainTurn('new', {answer:'new answer'}, c.brainScope());
    assert.equal(c.previousBrainTurn().question, 'new');
    assert.equal(c.previousBrainTurn().answer, 'new answer');
  });
  test(`${page}: public sources and service failures are not reasoning context`, () => {
    const {context: c} = harness();
    c.rememberBrainTurn('sports', {answer:'public fixture',fact_label:'LIVE WEB SOURCES'}, c.brainScope());
    assert.equal(c.previousBrainTurn(), null);
    c.rememberBrainTurn('problem', {answer:'service failure',verification_status:'unavailable'}, c.brainScope());
    assert.equal(c.previousBrainTurn(), null);
  });
  test(`${page}: account and organization changes discard prior context and in-flight replies`, () => {
    const h = harness(), c = h.context, oldScope = c.brainScope();
    c.rememberBrainTurn('private question', {answer:'private answer'}, oldScope);
    h.account('fixture-account-b');
    assert.equal(c.previousBrainTurn(), null);
    c.rememberBrainTurn('late private question', {answer:'late answer'}, oldScope);
    assert.equal(c.previousBrainTurn(), null);
    c.rememberBrainTurn('another question', {answer:'another answer'}, c.brainScope());
    h.organization('fixture-org-b');
    assert.equal(c.previousBrainTurn(), null);
  });
}
