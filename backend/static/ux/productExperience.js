"use strict";

/**
 * productExperience.js
 * Additive UX runtime for conversation search, pinning, workflow center,
 * business tagging, trust diagnostics, and first-run setup.
 */

(function (global) {
  var STORAGE_PREFIX = "amicor_product_experience";
  var MAX_SNIPPET = 120;

  function nowIso() {
    return new Date().toISOString();
  }

  function uid(prefix) {
    return String(prefix || "id") + "_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
  }

  function createMemoryStorage() {
    var map = Object.create(null);
    return {
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null; },
      setItem: function (k, v) { map[k] = String(v); },
      removeItem: function (k) { delete map[k]; },
    };
  }

  function safeStorage() {
    try {
      if (global.localStorage) {
        var probe = "__amicor_probe__";
        global.localStorage.setItem(probe, "1");
        global.localStorage.removeItem(probe);
        return global.localStorage;
      }
    } catch (_) {}
    return createMemoryStorage();
  }

  function parseJson(text, fallback) {
    if (!text) return fallback;
    try { return JSON.parse(text); } catch (_) { return fallback; }
  }

  function limitText(text, maxLen) {
    var value = String(text || "").trim();
    if (!value) return "";
    if (value.length <= maxLen) return value;
    return value.slice(0, maxLen - 1).trimEnd() + "...";
  }

  function inferBusinessTags(text) {
    var source = String(text || "").toLowerCase();
    var tags = [];

    if (/lead|prospect|pipeline|crm|account/.test(source)) tags.push("crm");
    if (/invoice|billing|payment|receipt|expense/.test(source)) tags.push("finance");
    if (/meeting|schedule|calendar|follow\-up|agenda/.test(source)) tags.push("operations");
    if (/proposal|contract|client|deal|renewal/.test(source)) tags.push("sales");
    if (/support|ticket|incident|sla|escalation/.test(source)) tags.push("support");

    return tags.length ? tags : ["general"];
  }

  function buildTrustSnapshot(input) {
    var data = input || {};
    var diagnostics = data.diagnostics || {};
    var monitor = data.monitor || {};

    var errorRate = typeof diagnostics.errorRate === "number"
      ? diagnostics.errorRate
      : (typeof monitor.errorRate === "number" ? monitor.errorRate * 100 : 0);

    var avgLatency = typeof diagnostics.avgLatency === "number"
      ? diagnostics.avgLatency
      : (monitor.responseTimes && monitor.responseTimes.avg) || 0;

    var health = monitor.heartbeatOk === false ? "degraded" : "healthy";
    if (errorRate >= 20 || avgLatency > 2500) health = "degraded";
    if (errorRate >= 40 || avgLatency > 4000) health = "critical";

    return {
      generatedAt: nowIso(),
      health: health,
      errorRate: Math.round(errorRate * 10) / 10,
      avgLatencyMs: Math.round(avgLatency),
      totalRequests: diagnostics.totalRequests || monitor.totalRequests || 0,
      hints: [
        health === "critical" ? "High operational risk. Switch to fallback workflows." : null,
        avgLatency > 2500 ? "Responses are slower than target. Consider retries and lighter prompts." : null,
        errorRate > 15 ? "Error rate is elevated. Inspect provider status and deployment health." : null,
      ].filter(Boolean),
    };
  }

  function createConversationVault(options) {
    var opts = options || {};
    var storage = opts.storage || safeStorage();
    var namespace = opts.namespace || "guest";
    var key = STORAGE_PREFIX + "_conversations_" + namespace;

    function load() {
      var state = parseJson(storage.getItem(key), null);
      if (!state || !Array.isArray(state.conversations)) {
        return {
          activeConversationId: null,
          conversations: [],
        };
      }
      return state;
    }

    function save(state) {
      storage.setItem(key, JSON.stringify(state));
      return state;
    }

    function hasStoredMemory() {
      if (!global.AmiCorMemoryManager || typeof global.AmiCorMemoryManager.loadMemory !== "function") {
        return false;
      }
      try {
        var memory = global.AmiCorMemoryManager.loadMemory();
        var longTerm = (memory && memory.long_term_memory) || {};
        return !!(
          longTerm.user_name ||
          (Array.isArray(longTerm.preferences) && longTerm.preferences.length) ||
          (Array.isArray(longTerm.likes_dislikes) && longTerm.likes_dislikes.length) ||
          (Array.isArray(longTerm.goals) && longTerm.goals.length) ||
          (Array.isArray(longTerm.recurring_interests) && longTerm.recurring_interests.length) ||
          (Array.isArray(longTerm.active_projects) && longTerm.active_projects.length) ||
          (Array.isArray(longTerm.assistant_notes) && longTerm.assistant_notes.length)
        );
      } catch (_) {
        return false;
      }
    }

    function finalizeAssistantText(role, text, meta) {
      var normalizedRole = String(role || "").toLowerCase();
      if (normalizedRole !== "ai" && normalizedRole !== "assistant") {
        return String(text || "");
      }
      if (!global.AmiCorMemoryManager || typeof global.AmiCorMemoryManager.enforceAssistantVisibleResponse !== "function") {
        return String(text || "");
      }
      try {
        return global.AmiCorMemoryManager.enforceAssistantVisibleResponse(String(text || ""), {
          memoryEnabled: true,
          hasMemory: hasStoredMemory(),
          source: "product-experience-cache",
          responsePath: "cached-assistant-response",
          responseSourceIdentifier: meta && meta.tool ? meta.tool : "product-experience-cache",
          throwOnViolation: true,
        }).text;
      } catch (error) {
        if (error && error.code === global.AmiCorMemoryManager.POLICY_VIOLATION_CODE) {
          return error.replacementText || "I don't know that yet.";
        }
        throw error;
      }
    }

    function ensureActive(state, titleHint) {
      if (state.activeConversationId) {
        var existing = state.conversations.find(function (c) { return c.id === state.activeConversationId; });
        if (existing) return existing;
      }

      var conv = {
        id: uid("conv"),
        title: limitText(titleHint || "New Conversation", 48) || "New Conversation",
        pinned: false,
        createdAt: nowIso(),
        updatedAt: nowIso(),
        tags: [],
        messages: [],
      };
      state.conversations.unshift(conv);
      state.activeConversationId = conv.id;
      return conv;
    }

    function appendMessage(role, text, meta) {
      var state = load();
      var finalText = finalizeAssistantText(role, text, meta);
      var conversation = ensureActive(state, role === "user" ? finalText : "Amicor Chat");
      var message = {
        id: uid("msg"),
        role: role,
        text: String(finalText || ""),
        createdAt: nowIso(),
        meta: meta || {},
      };
      conversation.messages.push(message);
      conversation.updatedAt = nowIso();

      var inferred = inferBusinessTags(finalText);
      inferred.forEach(function (tag) {
        if (conversation.tags.indexOf(tag) === -1) conversation.tags.push(tag);
      });

      save(state);
      return message;
    }

    function setPinned(value) {
      var state = load();
      var conversation = ensureActive(state);
      conversation.pinned = !!value;
      conversation.updatedAt = nowIso();
      save(state);
      return conversation.pinned;
    }

    function isPinned() {
      var state = load();
      var conversation = ensureActive(state);
      return !!conversation.pinned;
    }

    function renameActive(title) {
      var state = load();
      var conversation = ensureActive(state);
      conversation.title = limitText(title, 48) || conversation.title;
      conversation.updatedAt = nowIso();
      save(state);
      return conversation.title;
    }

    function listConversations() {
      var state = load();
      return state.conversations.slice().sort(function (a, b) {
        var pinnedDelta = (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0);
        if (pinnedDelta !== 0) return pinnedDelta;
        return String(b.updatedAt).localeCompare(String(a.updatedAt));
      });
    }

    function search(query) {
      var q = String(query || "").trim().toLowerCase();
      if (!q) return [];

      var matches = [];
      listConversations().forEach(function (conv) {
        (conv.messages || []).forEach(function (msg) {
          var body = String(msg.text || "");
          if (body.toLowerCase().indexOf(q) === -1) return;
          matches.push({
            conversationId: conv.id,
            conversationTitle: conv.title,
            pinned: !!conv.pinned,
            role: msg.role,
            snippet: limitText(body, MAX_SNIPPET),
            createdAt: msg.createdAt,
          });
        });
      });

      return matches.slice(0, 30);
    }

    function exportState() {
      return load();
    }

    return {
      appendMessage: appendMessage,
      setPinned: setPinned,
      isPinned: isPinned,
      renameActive: renameActive,
      listConversations: listConversations,
      search: search,
      exportState: exportState,
    };
  }

  function createWorkflowCenter(options) {
    var opts = options || {};
    var storage = opts.storage || safeStorage();
    var namespace = opts.namespace || "guest";
    var key = STORAGE_PREFIX + "_workflows_" + namespace;

    function load() {
      var state = parseJson(storage.getItem(key), null);
      if (!state || !Array.isArray(state.templates) || !Array.isArray(state.runs)) {
        return { templates: [], runs: [] };
      }
      return state;
    }

    function save(state) {
      storage.setItem(key, JSON.stringify(state));
      return state;
    }

    function createTemplate(input) {
      var source = input || {};
      return {
        id: uid("wf"),
        name: limitText(source.name || "Workflow", 48),
        prompt: String(source.prompt || ""),
        actions: Array.isArray(source.actions) ? source.actions.slice() : [],
        tags: Array.isArray(source.tags) ? source.tags.slice() : inferBusinessTags(source.name || source.prompt || ""),
        createdAt: nowIso(),
        updatedAt: nowIso(),
      };
    }

    function saveTemplate(input) {
      var state = load();
      var template = createTemplate(input);
      state.templates.unshift(template);
      state.templates = state.templates.slice(0, 100);
      save(state);
      return template;
    }

    function listTemplates() {
      return load().templates.slice().sort(function (a, b) {
        return String(b.updatedAt).localeCompare(String(a.updatedAt));
      });
    }

    function runTemplate(templateId, context) {
      var state = load();
      var template = state.templates.find(function (t) { return t.id === templateId; });
      if (!template) {
        return { ok: false, error: "template-not-found" };
      }

      var start = Date.now();
      var run = {
        id: uid("run"),
        templateId: template.id,
        templateName: template.name,
        status: "completed",
        input: String(context || ""),
        steps: template.actions.length || 1,
        tags: template.tags.slice(),
        createdAt: nowIso(),
        durationMs: 0,
      };
      run.durationMs = Math.max(1, Date.now() - start);

      state.runs.unshift(run);
      state.runs = state.runs.slice(0, 200);
      save(state);

      return { ok: true, run: run };
    }

    function listRuns() {
      return load().runs.slice();
    }

    return {
      saveTemplate: saveTemplate,
      listTemplates: listTemplates,
      runTemplate: runTemplate,
      listRuns: listRuns,
    };
  }

  function setupWizard(storage, onComplete) {
    var key = STORAGE_PREFIX + "_setup_completed";
    function isDone() {
      return storage.getItem(key) === "1";
    }

    function complete(profile) {
      storage.setItem(key, "1");
      storage.setItem(STORAGE_PREFIX + "_profile", JSON.stringify(profile || {}));
      if (typeof onComplete === "function") onComplete(profile || {});
    }

    function reset() {
      storage.removeItem(key);
      storage.removeItem(STORAGE_PREFIX + "_profile");
    }

    return {
      isDone: isDone,
      complete: complete,
      reset: reset,
    };
  }

  function bindSearchUI(controller, refs) {
    if (!refs || !refs.searchInput || !refs.searchResults) return;

    refs.searchInput.addEventListener("input", function () {
      var q = refs.searchInput.value;
      var matches = controller.searchConversations(q);
      refs.searchResults.innerHTML = "";

      if (!q.trim()) {
        refs.searchResults.hidden = true;
        return;
      }

      if (!matches.length) {
        refs.searchResults.hidden = false;
        refs.searchResults.innerHTML = '<div class="conv-hit empty">No results found</div>';
        return;
      }

      refs.searchResults.hidden = false;
      matches.forEach(function (item) {
        var node = document.createElement("div");
        node.className = "conv-hit" + (item.pinned ? " pinned" : "");
        node.innerHTML =
          '<div class="conv-hit-title">' +
          (item.pinned ? "Pinned - " : "") +
          item.conversationTitle +
          '</div><div class="conv-hit-body">' +
          item.snippet +
          '</div>';
        refs.searchResults.appendChild(node);
      });
    });
  }

  function bindWorkflowUI(controller, refs) {
    if (!refs || !refs.workflowPanel) return;

    function renderTemplates() {
      if (!refs.workflowTemplates) return;
      refs.workflowTemplates.innerHTML = "";
      var templates = controller.listWorkflowTemplates();
      if (!templates.length) {
        refs.workflowTemplates.innerHTML = '<div class="workflow-empty">No saved workflows yet.</div>';
        return;
      }

      templates.forEach(function (template) {
        var node = document.createElement("div");
        node.className = "workflow-item";
        node.innerHTML =
          '<div class="workflow-name">' + template.name + '</div>' +
          '<div class="workflow-tags">' + template.tags.join(" | ") + '</div>';
        node.addEventListener("click", function () {
          var run = controller.runWorkflowTemplate(template.id, "ui-run");
          if (run.ok) renderRuns();
        });
        refs.workflowTemplates.appendChild(node);
      });
    }

    function renderRuns() {
      if (!refs.workflowRuns) return;
      refs.workflowRuns.innerHTML = "";
      var runs = controller.listWorkflowRuns();
      if (!runs.length) {
        refs.workflowRuns.innerHTML = '<div class="workflow-empty">No workflow runs yet.</div>';
        return;
      }

      runs.slice(0, 12).forEach(function (run) {
        var node = document.createElement("div");
        node.className = "workflow-run";
        node.textContent = run.templateName + " - " + run.status + " - " + run.durationMs + "ms";
        refs.workflowRuns.appendChild(node);
      });
    }

    if (refs.workflowSaveBtn && refs.workflowName && refs.workflowPrompt) {
      refs.workflowSaveBtn.addEventListener("click", function () {
        var name = refs.workflowName.value.trim();
        var prompt = refs.workflowPrompt.value.trim();
        if (!name) return;
        controller.saveWorkflowTemplate({
          name: name,
          prompt: prompt,
          actions: [
            { type: "chat", prompt: prompt || "Execute workflow" },
          ],
        });
        refs.workflowName.value = "";
        refs.workflowPrompt.value = "";
        renderTemplates();
      });
    }

    renderTemplates();
    renderRuns();

    return {
      renderTemplates: renderTemplates,
      renderRuns: renderRuns,
    };
  }

  function createController(options) {
    var opts = options || {};
    var storage = opts.storage || safeStorage();
    var namespace = opts.namespace || "guest";

    var conversationVault = createConversationVault({ storage: storage, namespace: namespace });
    var workflowCenter = createWorkflowCenter({ storage: storage, namespace: namespace });
    var wizard = setupWizard(storage, opts.onSetupComplete);

    var refs = opts.refs || {};
    var workflowRenderer = null;

    function updateTrustSnapshot() {
      if (!refs.trustStrip) return null;
      var snapshot = buildTrustSnapshot({
        diagnostics: global.AmiCorDiagnostics ? global.AmiCorDiagnostics.getSummary() : {},
        monitor: global.AmiCorMonitor ? global.AmiCorMonitor.getReport() : {},
      });
      refs.trustStrip.textContent =
        "Trust: " + snapshot.health + " | " +
        "Error " + snapshot.errorRate + "% | " +
        "Latency " + snapshot.avgLatencyMs + "ms";
      refs.trustStrip.className = "trust-strip " + snapshot.health;
      return snapshot;
    }

    if (refs.workflowToggleBtn && refs.workflowPanel) {
      refs.workflowToggleBtn.addEventListener("click", function () {
        refs.workflowPanel.hidden = !refs.workflowPanel.hidden;
      });
    }

    if (refs.pinBtn) {
      var syncPinButton = function () {
        var pinned = conversationVault.isPinned();
        refs.pinBtn.textContent = pinned ? "Pinned" : "Pin Chat";
      };
      refs.pinBtn.addEventListener("click", function () {
        conversationVault.setPinned(!conversationVault.isPinned());
        syncPinButton();
      });
      syncPinButton();
    }

    if (refs.refreshTrustBtn) {
      refs.refreshTrustBtn.addEventListener("click", function () {
        updateTrustSnapshot();
      });
    }

    function trackMessage(role, text, meta) {
      var msg = conversationVault.appendMessage(role, text, meta);
      if (role === "user") {
        conversationVault.renameActive(limitText(text, 48));
      }
      return msg;
    }

    var controllerApi = {
      trackMessage: trackMessage,
      setConversationPinned: conversationVault.setPinned,
      isConversationPinned: conversationVault.isPinned,
      searchConversations: conversationVault.search,
      listConversations: conversationVault.listConversations,
      exportConversations: conversationVault.exportState,
      saveWorkflowTemplate: workflowCenter.saveTemplate,
      listWorkflowTemplates: workflowCenter.listTemplates,
      runWorkflowTemplate: workflowCenter.runTemplate,
      listWorkflowRuns: workflowCenter.listRuns,
      inferBusinessTags: inferBusinessTags,
      buildTrustSnapshot: buildTrustSnapshot,
      updateTrustSnapshot: updateTrustSnapshot,
      isSetupCompleted: wizard.isDone,
      completeSetup: wizard.complete,
      resetSetup: wizard.reset,
      refreshWorkflowPanel: function () {
        if (workflowRenderer && workflowRenderer.renderTemplates) workflowRenderer.renderTemplates();
        if (workflowRenderer && workflowRenderer.renderRuns) workflowRenderer.renderRuns();
      },
    };

    bindSearchUI(controllerApi, refs);
    workflowRenderer = bindWorkflowUI(controllerApi, refs);
    updateTrustSnapshot();

    return controllerApi;
  }

  var AmiCorProductExperience = {
    createConversationVault: createConversationVault,
    createWorkflowCenter: createWorkflowCenter,
    inferBusinessTags: inferBusinessTags,
    buildTrustSnapshot: buildTrustSnapshot,
    createController: createController,
  };

  global.AmiCorProductExperience = AmiCorProductExperience;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = AmiCorProductExperience;
  }
})(typeof window !== "undefined" ? window : global);
