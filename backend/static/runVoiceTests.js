#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const AmiCorVoiceRuntime = require("./ux/voiceRuntime.js");

let passed = 0;
let failed = 0;

function ok(condition, label) {
  if (condition) {
    passed += 1;
    console.log("  ✓", label);
  } else {
    failed += 1;
    console.error("  ✗", label);
  }
}

function test(name, fn) {
  process.stdout.write(`\n${name}\n`);
  try {
    fn();
  } catch (err) {
    failed += 1;
    console.error("  ✗ THREW:", err.message || err);
  }
}

function summary() {
  console.log(`\n${"─".repeat(52)}`);
  console.log(`Results: ${passed} passed, ${failed} failed`);
  console.log("─".repeat(52));
  process.exit(failed > 0 ? 1 : 0);
}

test("Voice runtime helper exports", () => {
  ok(typeof AmiCorVoiceRuntime === "object", "module exports an object");
  ok(typeof AmiCorVoiceRuntime.createVoiceRuntimeController === "function", "factory is available");
  ok(AmiCorVoiceRuntime.VOICE_RUNTIME_STATES.idle === "idle", "idle state is exported");
});

test("Voice runtime transitions are explicit", () => {
  const runtime = AmiCorVoiceRuntime.createVoiceRuntimeController();

  ok(runtime.getSnapshot().runtimeState === "idle", "starts idle");
  runtime.setPermission("granted", "test-permission");
  runtime.setMuted(true, "test-mute");
  ok(!runtime.canStartListening(), "muted runtime cannot start listening");

  runtime.setMuted(false, "test-unmute");
  runtime.setListening("test-listening");
  ok(runtime.getSnapshot().listening === true, "listening flag is set");
  ok(runtime.getStatusLabel() === "LISTENING", "label reflects listening state");

  runtime.setProcessing("test-processing");
  ok(runtime.getSnapshot().runtimeState === "processing", "processing state is tracked");

  runtime.setSpeaking("test-speaking");
  ok(runtime.getSnapshot().speaking === true, "speaking flag is set");

  runtime.markInterrupted("test-interrupt");
  ok(runtime.getSnapshot().runtimeState === "idle", "interrupt returns runtime to idle");

  runtime.setDisconnected(true, "test-offline");
  ok(runtime.getSnapshot().runtimeState === "disconnected", "disconnect state is tracked");
  ok(!runtime.canStartListening(), "disconnected runtime cannot start listening");

  runtime.setDisconnected(false, "test-online");
  ok(runtime.getSnapshot().runtimeState === "idle", "reconnect returns to idle");
});

test("Voice runtime error state is visible", () => {
  const runtime = AmiCorVoiceRuntime.createVoiceRuntimeController();
  runtime.setError("permission_denied", "test-error");

  const snapshot = runtime.getSnapshot();
  ok(snapshot.runtimeState === "error", "error state is tracked");
  ok(snapshot.lastError === "permission_denied", "error reason is preserved");
  ok(runtime.getStatusLabel() === "ERROR", "label reflects error state");
});

test("Voice UI browser smoke contract is present", () => {
  const indexPath = path.join(__dirname, "index.html");
  const html = fs.readFileSync(indexPath, "utf8");

  ok(/id="btn-mic"/.test(html) && /Start Voice/.test(html), "Start Voice control is present");
  ok(/id="btn-voice-stop"/.test(html) && /Stop Voice/.test(html), "Stop Voice control is present");
  ok(/id="btn-voice-retry"/.test(html) && /Retry/.test(html), "Retry control is present");
  ok(/id="btn-voice-mute"/.test(html) && /Mute Mic/.test(html), "Mute Mic control is present");
  ok(/id="btn-voice-interrupt"/.test(html) && /Interrupt Assistant/.test(html), "Interrupt Assistant control is present");
  ok(/id="btn-voice-test-raw"/.test(html) && /Test Raw Mic/.test(html), "Test Raw Mic control is present");
  ok(/id="btn-voice-export"/.test(html) && /Copy Diagnostics/.test(html), "Copy Diagnostics control is present");
  ok(/id="btn-voice-diag-toggle"/.test(html) && /Show Voice Diagnostics/.test(html), "Voice diagnostics toggle is present");
  ok(/id="voice-state-pill"/.test(html), "voice runtime state pill is present");
  ok(/voice-status-chips/.test(html), "voice status chips are present");
  ok(/voice-status-chip/.test(html), "voice status chip styles are present");
  ok(/id="voice-dev-panel"/.test(html), "voice diagnostics panel is present");
  ok(/voice-diagnostics-grid/.test(html), "voice diagnostics uses a responsive card grid");
  ok(/voice-diagnostic-card/.test(html), "voice diagnostics card layout is present");
  ok(/voice-diagnostic-row/.test(html), "voice diagnostics rows are present");
  ok(/id="voice-diag-permission"/.test(html), "voice diagnostics exposes permission state");
  ok(/id="voice-diag-secure"/.test(html), "voice diagnostics exposes secure context status");
  ok(/id="voice-diag-media"/.test(html), "voice diagnostics exposes mediaDevices availability");
  ok(/id="voice-diag-audio-input-count"/.test(html), "voice diagnostics exposes audio input count");
  ok(/id="voice-diag-audio-input-exists"/.test(html), "voice diagnostics exposes audio input existence");
  ok(/id="voice-diag-audio-input-default"/.test(html), "voice diagnostics exposes default audio input label");
  ok(/id="voice-diag-audio-input-devices"/.test(html), "voice diagnostics exposes enumerated audio inputs");
  ok(/id="voice-diag-recognition"/.test(html), "voice diagnostics exposes speech recognition support");
  ok(/id="voice-diag-state"/.test(html), "voice diagnostics exposes runtime state");
  ok(/id="voice-diag-error"/.test(html), "voice diagnostics exposes last mic error");
  ok(/id="voice-diag-raw-mic-test-status"/.test(html), "voice diagnostics exposes raw mic test status");
  ok(/id="voice-diag-raw-mic-test-error"/.test(html), "voice diagnostics exposes raw mic test error");
  ok(/id="voice-diag-raw-mic-test-tracks"/.test(html), "voice diagnostics exposes raw mic test tracks");
  ok(/id="voice-env-checklist"/.test(html), "manual environment checklist is present");
  ok(/max-height:\s*320px/.test(html), "diagnostics panel is height-limited");
  ok(/overflow-y:\s*auto/.test(html), "diagnostics panel scrolls internally");
  ok(/position:\s*sticky/.test(html), "voice action bar uses sticky positioning");
  ok(/function\s+runVoiceUiBrowserSmoke\s*\(/.test(html), "browser smoke helper is defined");
  ok(/elementFromPoint/.test(html), "browser smoke helper asserts real hit targets");
  ok(/focus\(\{\s*preventScroll:\s*true\s*\}\)/.test(html), "browser smoke helper asserts focusability");
  ok(/function\s+runUnifiedLocalhostIntegrationVerification\s*\(/.test(html), "localhost live verification helper is defined");
  ok(/function\s+markStartupStep\s*\(/.test(html), "startup orchestration tracer is defined");
  ok(/STARTUP_ORCHESTRATION_STEP/.test(html), "startup orchestration step events are emitted");
  ok(/EXPECTED_LOCAL_RUNTIME_ORIGIN\s*=\s*"http:\/\/127\.0\.0\.1:8011"/.test(html), "localhost runtime target is enforced");
  ok(/\[RUNTIME_ENV_LOCALHOST\]/.test(html), "localhost runtime env tag is present");
  ok(/\[RUNTIME_ENV_FILE_MODE\]/.test(html), "file mode runtime env tag is present");
  ok(/\[SECURE_CONTEXT_CONFIRMED\]/.test(html), "secure context tag is present");
  ok(/\[VOICE_RUNTIME_READY\]/.test(html), "voice runtime ready tag is present");
  ok(/\[MEMORY_RUNTIME_READY\]/.test(html), "memory runtime ready tag is present");
  ok(/\[DIAGNOSTICS_RUNTIME_READY\]/.test(html), "diagnostics runtime ready tag is present");
  ok(/AmiCorVoiceDebug/.test(html), "voice debug API is exposed to browser runtime");
  ok(/runLiveVerification/.test(html), "voice debug API exposes live localhost verification entry point");
  ok(/getIntegratedState/.test(html), "voice debug API exposes integrated-state assertion entry point");
  ok(/exportDiagnostics/.test(html), "voice debug API exposes export diagnostics entry point");
  ok(/testRawMic/.test(html), "voice debug API exposes raw mic test entry point");
});

test("Permission precheck bypass is implemented", () => {
  const indexPath = path.join(__dirname, "index.html");
  const html = fs.readFileSync(indexPath, "utf8");

  ok(/permissionPrecheck/.test(html), "permissionPrecheck field is tracked in diagnostics");
  ok(/permissionPrecheckBlockedStartup/.test(html), "permissionPrecheckBlockedStartup flag exists");
  ok(/getUserMediaAttempted/.test(html), "getUserMediaAttempted flag exists");
  ok(/getUserMediaResult/.test(html), "getUserMediaResult field exists");
  ok(/getUserMediaErrorName/.test(html), "getUserMediaErrorName field exists");
  ok(/getUserMediaErrorMessage/.test(html), "getUserMediaErrorMessage field exists");
  ok(/MIC_PERMISSION_PRECHECK_DENIED/.test(html), "permission precheck denied event is logged (but not terminal)");
  ok(/MIC_PERMISSION_DENIED_BY_GETUSERMEDIA/.test(html), "getUserMedia denial is distinguished from precheck");
  ok(/MIC_PERMISSION_PRECHECK_DENIAL_OVERRIDDEN/.test(html), "overridden precheck event is emitted when precheck denied but getUserMedia granted");
  ok(/MIC_RAW_TEST_START/.test(html), "raw mic test start event is logged");
  ok(/MIC_RAW_TEST_SUCCESS/.test(html), "raw mic test success event is logged");
  ok(/MIC_RAW_TEST_FAILED/.test(html), "raw mic test failure event is logged");
  ok(/MIC_DEVICE_ENUMERATED/.test(html), "device enumeration event is logged");
  ok(/MIC_DEVICE_ENUMERATION_FAILED/.test(html), "device enumeration failure event is logged");
  ok(/id="voice-diag-permission-precheck"/.test(html), "permission precheck diagnostic field is visible");
  ok(/id="voice-diag-get-user-media-attempted"/.test(html), "getUserMedia attempted diagnostic is visible");
  ok(/id="voice-diag-get-user-media-result"/.test(html), "getUserMedia result diagnostic is visible");
  ok(/MIC_BLOCKED_BY_BROWSER_OR_OS/.test(html), "blocked microphone classification is present");
  ok(/id="voice-diag-raw-mic-test-status"/.test(html), "raw mic test diagnostics are visible");
  ok(/voice-diag-toggle-btn/.test(html), "diagnostics toggle button styling is present");
  ok(/ALWAYS attempt getUserMedia regardless of permission precheck result/.test(html), "bypass comment is in code");
});

summary();