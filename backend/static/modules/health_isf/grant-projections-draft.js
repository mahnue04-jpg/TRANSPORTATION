/**
 * Pure draft helpers for Grant Command Center financial projection inputs.
 * Keeps in-progress edits durable across re-renders without marking assumptions READY.
 */
(function (root) {
  "use strict";

  function upsertScenarioDraft(store, scenarioKey, assumptions, options) {
    options = options || {};
    var next = Object.assign({}, store && typeof store === "object" ? store : {});
    var scenarios = Object.assign({}, next.scenarios && typeof next.scenarios === "object" ? next.scenarios : {});
    var key = String(scenarioKey || next.active_scenario || "conservative");
    scenarios[key] = Object.assign({}, assumptions && typeof assumptions === "object" ? assumptions : {});
    next.scenarios = scenarios;
    next.active_scenario = String(options.activeScenario || next.active_scenario || key);
    if (options.markSaved) {
      next.saved_complete = !!options.savedComplete;
      next.saved_at = options.savedAt || new Date().toISOString();
    }
    return next;
  }

  function resolveAssumptions(defaultScenarios, draft, scenarioKey) {
    var key = String(scenarioKey || (draft && draft.active_scenario) || "conservative");
    var defaultsRoot = defaultScenarios && typeof defaultScenarios === "object" ? defaultScenarios : {};
    var defaultBundle = defaultsRoot[key] || {};
    var defaultAssumptions = defaultBundle.assumptions && typeof defaultBundle.assumptions === "object"
      ? defaultBundle.assumptions
      : defaultBundle;
    var draftScenarios = draft && draft.scenarios && typeof draft.scenarios === "object" ? draft.scenarios : {};
    var draftAssumptions = draftScenarios[key] && typeof draftScenarios[key] === "object" ? draftScenarios[key] : {};
    return Object.assign({}, defaultAssumptions || {}, draftAssumptions || {});
  }

  function switchScenarioPreservingDraft(store, fromKey, toKey, liveAssumptions) {
    var preserved = upsertScenarioDraft(store, fromKey, liveAssumptions, {
      activeScenario: String(fromKey || "conservative"),
    });
    preserved.active_scenario = String(toKey || "conservative");
    return preserved;
  }

  function resetDraft() {
    return null;
  }

  root.AmicorGrantProjectionDraft = {
    upsertScenarioDraft: upsertScenarioDraft,
    resolveAssumptions: resolveAssumptions,
    switchScenarioPreservingDraft: switchScenarioPreservingDraft,
    resetDraft: resetDraft,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = root.AmicorGrantProjectionDraft;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
