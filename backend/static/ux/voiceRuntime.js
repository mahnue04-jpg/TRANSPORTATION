"use strict";

(function(global) {

const VOICE_RUNTIME_STATES = Object.freeze({
  idle: "idle",
  listening: "listening",
  processing: "processing",
  speaking: "speaking",
  error: "error",
  disconnected: "disconnected",
});

function cloneSnapshot(state) {
  return Object.assign({}, state);
}

function createVoiceRuntimeController(options) {
  const config = Object.assign({ onChange: null, onEvent: null }, options || {});
  const state = {
    runtimeState: VOICE_RUNTIME_STATES.idle,
    previousState: null,
    resumeState: VOICE_RUNTIME_STATES.idle,
    permission: "unknown",
    muted: false,
    listening: false,
    speaking: false,
    disconnected: false,
    interrupted: false,
    lastError: null,
    lastReason: "boot",
    lastAction: "boot",
    lastUpdated: new Date().toISOString(),
  };

  function emit(type, payload) {
    if (typeof config.onEvent !== "function") return;
    try {
      config.onEvent(type, Object.assign({ ts: new Date().toISOString() }, payload || {}, {
        snapshot: cloneSnapshot(state),
      }));
    } catch (_) {}
  }

  function notify(reason) {
    if (typeof config.onChange !== "function") return;
    try {
      config.onChange(cloneSnapshot(state), reason || state.lastReason || "runtime");
    } catch (_) {}
  }

  function setMode(nextState, reason, fields) {
    const normalized = VOICE_RUNTIME_STATES[nextState] || nextState;
    if (!normalized || !Object.prototype.hasOwnProperty.call(VOICE_RUNTIME_STATES, normalized)) {
      return cloneSnapshot(state);
    }

    const previous = state.runtimeState;
    if (previous === VOICE_RUNTIME_STATES.disconnected && normalized !== VOICE_RUNTIME_STATES.disconnected) {
      state.disconnected = false;
    }
    if (normalized === VOICE_RUNTIME_STATES.disconnected && previous !== VOICE_RUNTIME_STATES.disconnected) {
      state.resumeState = previous || VOICE_RUNTIME_STATES.idle;
      state.disconnected = true;
    }

    state.previousState = previous;
    state.runtimeState = normalized;
    state.lastReason = reason || "runtime";
    state.lastAction = reason || "runtime";
    state.lastUpdated = new Date().toISOString();
    state.listening = normalized === VOICE_RUNTIME_STATES.listening;
    state.speaking = normalized === VOICE_RUNTIME_STATES.speaking;
    state.disconnected = normalized === VOICE_RUNTIME_STATES.disconnected;
    if (normalized !== VOICE_RUNTIME_STATES.error && state.lastError === "") {
      state.lastError = null;
    }

    if (fields && typeof fields === "object") {
      Object.assign(state, fields);
    }

    emit("VOICE_RUNTIME_STATE_CHANGED", {
      previousState: previous,
      nextState: normalized,
      reason: state.lastReason,
    });
    notify(reason);
    return cloneSnapshot(state);
  }

  function setPermission(permission, reason) {
    state.permission = permission || "unknown";
    state.lastReason = reason || "permission-change";
    state.lastUpdated = new Date().toISOString();
    emit("MIC_PERMISSION_STATE_CHANGED", {
      permission: state.permission,
      reason: state.lastReason,
    });
    notify(reason);
    return cloneSnapshot(state);
  }

  function setMuted(muted, reason) {
    state.muted = !!muted;
    state.lastReason = reason || "mute-change";
    state.lastUpdated = new Date().toISOString();
    emit("VOICE_RUNTIME_MUTED_CHANGED", {
      muted: state.muted,
      reason: state.lastReason,
    });
    notify(reason);
    return cloneSnapshot(state);
  }

  function setDisconnected(disconnected, reason) {
    if (disconnected) {
      if (!state.disconnected) {
        state.resumeState = state.runtimeState || VOICE_RUNTIME_STATES.idle;
      }
      return setMode(VOICE_RUNTIME_STATES.disconnected, reason || "disconnected");
    }

    const resumeState = state.resumeState && state.resumeState !== VOICE_RUNTIME_STATES.disconnected
      ? state.resumeState
      : VOICE_RUNTIME_STATES.idle;
    state.resumeState = VOICE_RUNTIME_STATES.idle;
    return setMode(resumeState, reason || "reconnected", { disconnected: false });
  }

  function setListening(reason, fields) {
    return setMode(VOICE_RUNTIME_STATES.listening, reason || "listening", fields);
  }

  function setProcessing(reason, fields) {
    return setMode(VOICE_RUNTIME_STATES.processing, reason || "processing", fields);
  }

  function setSpeaking(reason, fields) {
    return setMode(VOICE_RUNTIME_STATES.speaking, reason || "speaking", fields);
  }

  function setIdle(reason, fields) {
    state.interrupted = false;
    return setMode(VOICE_RUNTIME_STATES.idle, reason || "idle", fields);
  }

  function setError(error, reason, fields) {
    const nextFields = Object.assign({}, fields || {}, {
      lastError: error ? String(error) : state.lastError,
    });
    return setMode(VOICE_RUNTIME_STATES.error, reason || "error", nextFields);
  }

  function markInterrupted(reason) {
    state.interrupted = true;
    emit("VOICE_RUNTIME_INTERRUPTED", {
      reason: reason || "interrupted",
    });
    return setIdle(reason || "interrupted");
  }

  function clearInterrupted(reason) {
    state.interrupted = false;
    emit("VOICE_RUNTIME_INTERRUPT_CLEARED", {
      reason: reason || "interrupt-cleared",
    });
    notify(reason || "interrupt-cleared");
    return cloneSnapshot(state);
  }

  function canStartListening() {
    return !state.muted && !state.disconnected && state.permission !== "denied";
  }

  function canStop() {
    return state.runtimeState !== VOICE_RUNTIME_STATES.idle;
  }

  function getStatusLabel() {
    switch (state.runtimeState) {
      case VOICE_RUNTIME_STATES.listening:
        return "LISTENING";
      case VOICE_RUNTIME_STATES.processing:
        return "PROCESSING";
      case VOICE_RUNTIME_STATES.speaking:
        return "SPEAKING";
      case VOICE_RUNTIME_STATES.error:
        return "ERROR";
      case VOICE_RUNTIME_STATES.disconnected:
        return "DISCONNECTED";
      default:
        return "IDLE";
    }
  }

  function getSnapshot() {
    return cloneSnapshot(state);
  }

  return {
    states: VOICE_RUNTIME_STATES,
    getSnapshot,
    getStatusLabel,
    canStartListening,
    canStop,
    setPermission,
    setMuted,
    setDisconnected,
    setListening,
    setProcessing,
    setSpeaking,
    setIdle,
    setError,
    markInterrupted,
    clearInterrupted,
  };
}

const AmiCorVoiceRuntime = {
  VOICE_RUNTIME_STATES,
  createVoiceRuntimeController,
};

if (typeof window !== "undefined") {
  window.AmiCorVoiceRuntime = AmiCorVoiceRuntime;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = AmiCorVoiceRuntime;
}

}(typeof window !== "undefined" ? window : global));