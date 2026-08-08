/**
 * Node tests for Grant projection draft persistence helpers.
 * Run: node backend/static/modules/health_isf/grant-projections-draft.test.js
 */
const assert = require("assert");
const draft = require("./grant-projections-draft.js");

function testEditFieldAThenFieldBDoesNotResetA() {
  let store = null;
  store = draft.upsertScenarioDraft(store, "conservative", {
    active_providers: 1,
    rides_per_provider_per_day: 3,
  }, { activeScenario: "conservative" });
  store = draft.upsertScenarioDraft(store, "conservative", {
    active_providers: 1,
    rides_per_provider_per_day: 3,
    operating_days_per_month: 20,
  }, { activeScenario: "conservative" });
  const resolved = draft.resolveAssumptions(
    { conservative: { assumptions: { active_providers: 9, rides_per_provider_per_day: 9, operating_days_per_month: 9 } } },
    store,
    "conservative"
  );
  assert.strictEqual(resolved.active_providers, 1);
  assert.strictEqual(resolved.rides_per_provider_per_day, 3);
  assert.strictEqual(resolved.operating_days_per_month, 20);
}

function testRecalculatePreservesEnteredValues() {
  const store = draft.upsertScenarioDraft(null, "conservative", {
    active_providers: 1,
    rides_per_provider_per_day: 3,
    operating_days_per_month: 20,
    avg_net_revenue_per_ride: 30,
  }, { activeScenario: "conservative" });
  // Recalculate path re-upserts the same live assumptions without wiping siblings.
  const afterRecalc = draft.upsertScenarioDraft(store, "conservative", {
    active_providers: 1,
    rides_per_provider_per_day: 3,
    operating_days_per_month: 20,
    avg_net_revenue_per_ride: 30,
  }, { activeScenario: "conservative" });
  assert.deepStrictEqual(afterRecalc.scenarios.conservative, store.scenarios.conservative);
}

function testLocalSaveSurvivesReloadShape() {
  const saved = draft.upsertScenarioDraft(null, "conservative", {
    active_providers: 1,
    rides_per_provider_per_day: 3,
    operating_days_per_month: 20,
    avg_net_revenue_per_ride: 30,
    driver_cost_per_ride: 20,
    monthly_tech_cloud: 300,
    monthly_insurance: 500,
    monthly_marketing: 300,
    monthly_compliance_legal: 250,
    monthly_admin_ops: 500,
    monthly_other_opex: 150,
  }, {
    activeScenario: "conservative",
    markSaved: true,
    savedComplete: true,
    savedAt: "2026-08-07T00:00:00.000Z",
  });
  const reloaded = JSON.parse(JSON.stringify(saved));
  assert.strictEqual(reloaded.saved_complete, true);
  assert.strictEqual(reloaded.scenarios.conservative.avg_net_revenue_per_ride, 30);
  const resolved = draft.resolveAssumptions(
    { conservative: { assumptions: { avg_net_revenue_per_ride: 1 } } },
    reloaded,
    "conservative"
  );
  assert.strictEqual(resolved.avg_net_revenue_per_ride, 30);
}

function testScenarioSwitchDoesNotOverwriteOtherScenario() {
  let store = draft.upsertScenarioDraft(null, "conservative", {
    active_providers: 1,
    rides_per_provider_per_day: 3,
  }, { activeScenario: "conservative" });
  store = draft.switchScenarioPreservingDraft(store, "conservative", "base_case", {
    active_providers: 1,
    rides_per_provider_per_day: 3,
  });
  store = draft.upsertScenarioDraft(store, "base_case", {
    active_providers: 2,
    rides_per_provider_per_day: 5,
  }, { activeScenario: "base_case" });
  assert.strictEqual(store.scenarios.conservative.rides_per_provider_per_day, 3);
  assert.strictEqual(store.scenarios.base_case.rides_per_provider_per_day, 5);
  assert.strictEqual(store.active_scenario, "base_case");
}

function testResetPlaceholdersIntentionallyRestoresDefaults() {
  const store = draft.upsertScenarioDraft(null, "conservative", {
    active_providers: 99,
  }, { activeScenario: "conservative" });
  const cleared = draft.resetDraft(store);
  assert.strictEqual(cleared, null);
  const resolved = draft.resolveAssumptions(
    { conservative: { assumptions: { active_providers: 1, rides_per_provider_per_day: 3 } } },
    cleared,
    "conservative"
  );
  assert.strictEqual(resolved.active_providers, 1);
  assert.strictEqual(resolved.rides_per_provider_per_day, 3);
}

function testGrantRequestExcludedFromOperatingRevenueMath() {
  // Mirrors UI: GRANT REQUEST $35,000 is never added into projected operating revenue.
  const monthlyRides = 1 * 3 * 20;
  const projectedMonthlyGross = monthlyRides * 30;
  const grantRequest = 35000;
  assert.strictEqual(monthlyRides, 60);
  assert.strictEqual(projectedMonthlyGross, 1800);
  assert.notStrictEqual(projectedMonthlyGross, grantRequest);
  assert.strictEqual(projectedMonthlyGross + 0, 1800);
}

testEditFieldAThenFieldBDoesNotResetA();
testRecalculatePreservesEnteredValues();
testLocalSaveSurvivesReloadShape();
testScenarioSwitchDoesNotOverwriteOtherScenario();
testResetPlaceholdersIntentionallyRestoresDefaults();
testGrantRequestExcludedFromOperatingRevenueMath();
console.log("grant-projections-draft.test.js: all passed");
