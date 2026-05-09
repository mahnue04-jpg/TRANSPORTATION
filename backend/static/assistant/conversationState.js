"use strict";

const { ASSISTANT_STATES, cloneAssistantValue } = require("./assistantSchemas");

function createConversationState(conversationId) {
  var id = String(conversationId || "conversation");
  var state = ASSISTANT_STATES.idle;
  var messages = [];
  var events = [];
  var interrupted = false;
  var interruptReason = null;

  function addEvent(type, payload) {
    events.push({ at: Date.now(), type: type, payload: cloneAssistantValue(payload || {}) });
  }

  function setState(next, payload) {
    state = next;
    addEvent("state", { state: next, payload: payload || {} });
  }

  function addMessage(role, text, metadata) {
    messages.push({
      id: "msg-" + Date.now() + "-" + Math.floor(Math.random() * 10000),
      at: Date.now(),
      role: String(role || "assistant"),
      text: String(text || ""),
      metadata: cloneAssistantValue(metadata || {}),
    });
  }

  function interrupt(reason) {
    interrupted = true;
    interruptReason = reason ? String(reason) : "interrupted";
    setState(ASSISTANT_STATES.interrupted, { reason: interruptReason });
  }

  function clearInterrupt() {
    interrupted = false;
    interruptReason = null;
  }

  function snapshot() {
    return {
      conversationId: id,
      state: state,
      interrupted: interrupted,
      interruptReason: interruptReason,
      messages: cloneAssistantValue(messages),
      events: cloneAssistantValue(events),
    };
  }

  return {
    get conversationId() {
      return id;
    },
    get state() {
      return state;
    },
    get interrupted() {
      return interrupted;
    },
    get interruptReason() {
      return interruptReason;
    },
    addEvent: addEvent,
    setState: setState,
    addMessage: addMessage,
    interrupt: interrupt,
    clearInterrupt: clearInterrupt,
    snapshot: snapshot,
  };
}

module.exports = {
  createConversationState: createConversationState,
};
