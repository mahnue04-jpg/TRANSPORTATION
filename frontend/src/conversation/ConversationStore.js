"use strict";

const {
  ASSISTANT_UI_STATES,
  TERMINAL_STATES,
  cloneConversationValue,
  createConversationMessage,
  createConversationSession,
} = require("./ConversationSchemas");

function createConversationStore(options) {
  var config = Object.assign(
    {
      storageKey: "amicor-conversations-v1",
      maxMessagesPerSession: 300,
      maxFeedEvents: 600,
      persist: true,
      storageAdapter: null,
    },
    options || {}
  );

  var sessions = Object.create(null);
  var activeSessionId = null;
  var listeners = [];

  function storage() {
    if (config.storageAdapter) {
      return config.storageAdapter;
    }
    if (typeof window !== "undefined" && window.localStorage) {
      return window.localStorage;
    }
    return null;
  }

  function notify() {
    var snapshot = getSnapshot();
    for (var i = 0; i < listeners.length; i++) {
      try {
        listeners[i](snapshot);
      } catch (_) {}
    }
  }

  function getActiveSession() {
    if (!activeSessionId || !sessions[activeSessionId]) {
      return null;
    }
    return sessions[activeSessionId];
  }

  function trimSession(session) {
    if (session.messages.length > config.maxMessagesPerSession) {
      session.messages = session.messages.slice(session.messages.length - config.maxMessagesPerSession);
    }
    if (session.executionFeed.length > config.maxFeedEvents) {
      session.executionFeed = session.executionFeed.slice(session.executionFeed.length - config.maxFeedEvents);
    }
    if (session.toolActivity.length > config.maxFeedEvents) {
      session.toolActivity = session.toolActivity.slice(session.toolActivity.length - config.maxFeedEvents);
    }
    if (session.workflowHistory.length > config.maxFeedEvents) {
      session.workflowHistory = session.workflowHistory.slice(session.workflowHistory.length - config.maxFeedEvents);
    }
  }

  function save() {
    if (!config.persist) {
      return;
    }
    var adapter = storage();
    if (!adapter || typeof adapter.setItem !== "function") {
      return;
    }

    var payload = {
      activeSessionId: activeSessionId,
      sessions: sessions,
      savedAt: Date.now(),
    };

    try {
      adapter.setItem(config.storageKey, JSON.stringify(payload));
    } catch (_) {}
  }

  function load() {
    var adapter = storage();
    if (!adapter || typeof adapter.getItem !== "function") {
      return;
    }
    try {
      var raw = adapter.getItem(config.storageKey);
      if (!raw) {
        return;
      }
      var parsed = JSON.parse(raw);
      var incoming = parsed && parsed.sessions ? parsed.sessions : {};
      var ids = Object.keys(incoming);
      for (var i = 0; i < ids.length; i++) {
        sessions[ids[i]] = createConversationSession(incoming[ids[i]]);
        trimSession(sessions[ids[i]]);
      }
      if (parsed.activeSessionId && sessions[parsed.activeSessionId]) {
        activeSessionId = parsed.activeSessionId;
      }
    } catch (_) {}
  }

  function createSession(input) {
    var session = createConversationSession(input || {});
    sessions[session.id] = session;
    activeSessionId = session.id;
    save();
    notify();
    return session;
  }

  function activateSession(sessionId) {
    if (!sessions[sessionId]) {
      return null;
    }
    activeSessionId = sessionId;
    notify();
    return sessions[sessionId];
  }

  function appendMessage(role, text, metadata) {
    var session = getActiveSession() || createSession({ title: "Conversation" });
    var message = createConversationMessage({ role: role, text: text, metadata: metadata || {} });
    session.messages.push(message);
    session.updatedAt = Date.now();
    trimSession(session);
    save();
    notify();
    return message;
  }

  function upsertStreamingMessage(role, text, metadata) {
    var session = getActiveSession() || createSession({ title: "Conversation" });
    var last = session.messages.length > 0 ? session.messages[session.messages.length - 1] : null;

    if (!last || !last.streaming || last.role !== role) {
      last = createConversationMessage({ role: role, text: "", streaming: true, metadata: metadata || {} });
      session.messages.push(last);
    }

    last.text += String(text || "");
    last.streaming = true;
    last.metadata = Object.assign({}, last.metadata || {}, metadata || {});

    session.updatedAt = Date.now();
    trimSession(session);
    save();
    notify();
    return cloneConversationValue(last);
  }

  function finalizeStreamingMessage(metadata) {
    var session = getActiveSession();
    if (!session || session.messages.length === 0) {
      return null;
    }
    var last = session.messages[session.messages.length - 1];
    if (!last.streaming) {
      return cloneConversationValue(last);
    }
    last.streaming = false;
    last.metadata = Object.assign({}, last.metadata || {}, metadata || {});
    save();
    notify();
    return cloneConversationValue(last);
  }

  function setAssistantState(nextState, details) {
    var session = getActiveSession() || createSession({ title: "Conversation" });
    session.assistantState = ASSISTANT_UI_STATES[nextState] ? nextState : ASSISTANT_UI_STATES.failed;
    session.executionFeed.push({
      at: Date.now(),
      type: "assistant-state",
      state: session.assistantState,
      details: cloneConversationValue(details || {}),
    });
    session.updatedAt = Date.now();
    trimSession(session);
    save();
    notify();
  }

  function addWorkflowEntry(entry) {
    var session = getActiveSession() || createSession({ title: "Conversation" });
    session.workflowHistory.push(cloneConversationValue(entry || {}));
    session.updatedAt = Date.now();
    trimSession(session);
    save();
    notify();
  }

  function addToolActivity(entry) {
    var session = getActiveSession() || createSession({ title: "Conversation" });
    session.toolActivity.push(cloneConversationValue(entry || {}));
    session.updatedAt = Date.now();
    trimSession(session);
    save();
    notify();
  }

  function setMemoryContext(memoryContext) {
    var session = getActiveSession() || createSession({ title: "Conversation" });
    session.memoryContext = cloneConversationValue(memoryContext || { summary: "", indicators: [] });
    session.updatedAt = Date.now();
    save();
    notify();
  }

  function addExecutionEvent(event) {
    var session = getActiveSession() || createSession({ title: "Conversation" });
    session.executionFeed.push(cloneConversationValue(event || {}));
    trimSession(session);
    save();
    notify();
  }

  function recoverFromDesync(input) {
    var source = input || {};
    var session = getActiveSession() || createSession({ title: "Conversation" });
    if (!ASSISTANT_UI_STATES[session.assistantState]) {
      session.assistantState = ASSISTANT_UI_STATES.failed;
    }
    if (source.forceTerminal && !TERMINAL_STATES[session.assistantState]) {
      session.assistantState = ASSISTANT_UI_STATES.interrupted;
    }
    session.executionFeed.push({
      at: Date.now(),
      type: "state-recovery",
      details: cloneConversationValue(source),
    });
    trimSession(session);
    save();
    notify();
    return cloneConversationValue(session);
  }

  function listSessions() {
    var ids = Object.keys(sessions).sort(function (a, b) {
      return sessions[b].updatedAt - sessions[a].updatedAt;
    });
    var out = [];
    for (var i = 0; i < ids.length; i++) {
      out.push({
        id: sessions[ids[i]].id,
        title: sessions[ids[i]].title,
        updatedAt: sessions[ids[i]].updatedAt,
        assistantState: sessions[ids[i]].assistantState,
      });
    }
    return out;
  }

  function getSnapshot() {
    return {
      activeSessionId: activeSessionId,
      activeSession: cloneConversationValue(getActiveSession()),
      sessions: cloneConversationValue(sessions),
      list: listSessions(),
    };
  }

  function subscribe(listener) {
    listeners.push(listener);
    return function unsubscribe() {
      listeners = listeners.filter(function (item) { return item !== listener; });
    };
  }

  load();

  return {
    createSession: createSession,
    activateSession: activateSession,
    appendMessage: appendMessage,
    upsertStreamingMessage: upsertStreamingMessage,
    finalizeStreamingMessage: finalizeStreamingMessage,
    setAssistantState: setAssistantState,
    addWorkflowEntry: addWorkflowEntry,
    addToolActivity: addToolActivity,
    setMemoryContext: setMemoryContext,
    addExecutionEvent: addExecutionEvent,
    recoverFromDesync: recoverFromDesync,
    listSessions: listSessions,
    getSnapshot: getSnapshot,
    subscribe: subscribe,
    save: save,
    load: load,
  };
}

module.exports = {
  createConversationStore: createConversationStore,
};
