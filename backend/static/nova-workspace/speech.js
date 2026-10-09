/* A persistent native player keeps generated audio usable when autoplay is blocked. */
(function () {
  'use strict';
  var generation = 0;
  var controller = null;
  var audioUrl = null;
  var player = document.getElementById('workspace-audio');
  function t(message) { return window.NovaWorkspaceLanguage.t(message); }
  function status(message) {
    document.getElementById('speech-status').textContent = t(message);
    document.querySelectorAll('[data-nova-voice-status]').forEach(function (el) { el.textContent = t(message); });
  }
  function stop() {
    generation++;
    if (controller) controller.abort();
    controller = null;
    player.pause();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = null;
    player.removeAttribute('src');
    player.classList.add('hidden');
    status('Stopped.');
  }
  async function speak(text) {
    stop();
    var requestGeneration = generation;
    controller = new AbortController();
    var selected = document.getElementById('answer-language').value || 'en';
    var language = selected === 'bilingual' ? 'so' : selected;
    status('Generating speech…');
    try {
      var session = window.AmiCorSession;
      var headers = Object.assign({ 'Content-Type': 'application/json' }, session && session.getAuthHeaders ? session.getAuthHeaders() : {});
      if (!headers.Authorization && session && session.getAccessToken) headers.Authorization = 'Bearer ' + session.getAccessToken();
      var response = await fetch('/api/voice/speak', {
        method: 'POST', headers: headers, signal: controller.signal,
        body: JSON.stringify({ text: String(text).slice(0, 8000), language: language, preferred_provider: language === 'so' ? 'azure_neural_voice' : 'openai_realtime_voice' })
      });
      if (!response.ok) throw new Error('speech_unavailable');
      var payload = await response.json();
      if (generation !== requestGeneration) return;
      if (!payload.audio_b64) throw new Error('empty_audio');
      var bytes = Uint8Array.from(atob(payload.audio_b64), function (c) { return c.charCodeAt(0); });
      audioUrl = URL.createObjectURL(new Blob([bytes], { type: payload.mime_type || 'audio/mpeg' }));
      player.src = audioUrl;
      player.classList.remove('hidden');
      status('Audio ready. Press Play below if you do not hear it.');
      // Autoplay failure is not a provider failure: leave the native Play control available.
      try { await player.play(); } catch (_) {}
    } catch (err) {
      if (generation === requestGeneration && err.name !== 'AbortError') status('Speech is unavailable. Your text remains available.');
    }
  }
  player.onerror = function () {
    if (!audioUrl) return;
    stop();
    status('Speech is unavailable. Your text remains available.');
  };
  player.onended = function () { status('Audio ready. Press Play below if you do not hear it.'); };
  window.addEventListener('pagehide', stop);
  window.addEventListener('nova-language-change', stop);
  window.NovaWorkspaceSpeech = { speak: speak, stop: stop };
})();
