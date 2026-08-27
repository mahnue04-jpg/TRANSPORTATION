(function () {
  const PERSONAS = {
    "ChatGPT Neutral": { rate: 1.0, pitch: 1.0, pauseMs: 55, chunkSize: 460 },
    "ChatGPT Warmer": { rate: 0.98, pitch: 1.03, pauseMs: 70, chunkSize: 430 },
    "ChatGPT Faster": { rate: 1.07, pitch: 0.99, pauseMs: 40, chunkSize: 520 },
    "Calm Assistant": { rate: 0.96, pitch: 0.98, pauseMs: 280, chunkSize: 180 },
    "Professional": { rate: 1.0, pitch: 0.98, pauseMs: 220, chunkSize: 200 },
    "Friendly": { rate: 1.04, pitch: 1.06, pauseMs: 180, chunkSize: 170 },
    "Fast Briefing": { rate: 1.16, pitch: 1.0, pauseMs: 80, chunkSize: 260 },
    "Warm Conversational": { rate: 1.0, pitch: 1.01, pauseMs: 50, chunkSize: 420 },
    "Focus Mode": { rate: 1.08, pitch: 0.96, pauseMs: 130, chunkSize: 220 },
  };

  const INTERNAL_TERMS = [
    /provider_error/gi,
    /meta\.intent/gi,
    /sports_live_data/gi,
    /short_term_memory/gi,
    /orchestr(?:ation|ator)/gi,
    /routing\s+labels?/gi,
    /\b(?:tool|route|intent|provider)\.[a-z_]+\b/gi,
  ];

  const ABBREVIATIONS = [
    [/\be\.g\.\b/gi, "for example"],
    [/\bi\.e\.\b/gi, "that is"],
    [/\bvs\.\b/gi, "versus"],
    [/\bETA\b/g, "estimated time of arrival"],
    [/\bASAP\b/g, "as soon as possible"],
    [/\bAPI\b/g, "A P I"],
    [/\bURL\b/g, "link"],
  ];

  const REWRITES = [
    [/\bprovider\s+failed\b/gi, "that source is unavailable right now"],
    [/\bdegraded\b/gi, "temporarily limited"],
    [/\bpartial\b/gi, "partially available"],
    [/\bcircuit\s+open\b/gi, "temporarily unavailable"],
    [/\blatency\b/gi, "response delay"],
    [/\bpipeline\b/gi, "flow"],
    [/\borchestration\b/gi, "coordination"],
  ];

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function normalizeWhitespace(text) {
    return String(text || "")
      .replace(/\s+/g, " ")
      .replace(/\s+([,.;!?])/g, "$1")
      .trim();
  }

  function sanitizeForSpeech(text) {
    let out = String(text || "");
    out = out.replace(/```[\s\S]*?```/g, " ");
    out = out.replace(/`[^`]*`/g, " ");
    out = out.replace(/<[^>]+>/g, " ");
    out = out.replace(/https?:\/\/\S+/g, " ");
    out = out.replace(/\[[^\]]+\]\([^\)]+\)/g, " ");
    out = out.replace(/[_*#~>|]+/g, " ");
    out = out.replace(/\b(?:meta|provider|route|routing|intent)\.[a-z_]+\b/gi, " ");
    INTERNAL_TERMS.forEach((pattern) => {
      out = out.replace(pattern, " ");
    });
    ABBREVIATIONS.forEach(([pattern, replacement]) => {
      out = out.replace(pattern, replacement);
    });
    REWRITES.forEach(([pattern, replacement]) => {
      out = out.replace(pattern, replacement);
    });
    out = normalizeWhitespace(out);
    return out || "I have a quick update for you.";
  }

  function chunkTextForSpeech(text, persona) {
    const maxLen = (persona && persona.chunkSize) || 200;
    const sentences = String(text || "")
      .split(/(?<=[.!?])\s+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const chunks = [];
    let current = "";
    sentences.forEach((sentence) => {
      if (!current) {
        current = sentence;
        return;
      }
      if ((current + " " + sentence).length <= maxLen) {
        current += " " + sentence;
      } else {
        chunks.push(current);
        current = sentence;
      }
    });
    if (current) chunks.push(current);
    if (!chunks.length && text) chunks.push(String(text));
    return chunks;
  }

  function base64ToBlob(base64Data, mimeType) {
    const binary = atob(base64Data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new Blob([bytes], { type: mimeType || "audio/mpeg" });
  }

  function createEngine(config = {}) {
    const apiBase = config.apiBase || "";
    const onState = typeof config.onState === "function" ? config.onState : function () {};
    const onDebug = typeof config.onDebug === "function" ? config.onDebug : function () {};
    const browserFallbackEnabled = config.browserFallbackEnabled === true;

    const state = {
      speaking: false,
      interrupted: false,
      queue: [],
      index: 0,
      controller: null,
      currentAudio: null,
      lastPersona: "Warm Conversational",
      resumeText: "",
    };

    async function voiceApiFetch(url, options) {
      const opts = options || {};
      if (typeof config.authFetch === "function") {
        return config.authFetch(url, opts);
      }
      if (window.AmiCorSession && typeof window.AmiCorSession.authFetch === "function") {
        return window.AmiCorSession.authFetch(url, opts);
      }
      return fetch(url, opts);
    }

    async function loadProviders() {
      try {
        const res = await voiceApiFetch(apiBase + "/api/voice/providers", { method: "GET" });
        if (!res.ok) return null;
        return await res.json();
      } catch (_) {
        return null;
      }
    }

    function stop(reason) {
      state.interrupted = true;
      state.speaking = false;
      if (state.controller) {
        try { state.controller.abort(reason || "voice-stop"); } catch (_) {}
      }
      state.controller = null;
      if (state.currentAudio) {
        try { state.currentAudio.pause(); } catch (_) {}
      }
      state.currentAudio = null;
      if (window.speechSynthesis) {
        try { window.speechSynthesis.cancel(); } catch (_) {}
      }
      onState({ speaking: false, reason: reason || "stopped" });
    }

    function fallbackBrowserSpeak(text, persona) {
      return new Promise((resolve) => {
        if (!browserFallbackEnabled || !window.speechSynthesis) {
          resolve(false);
          return;
        }
        try {
          const voices = window.speechSynthesis.getVoices ? window.speechSynthesis.getVoices() : [];
          const preferred = voices.find((v) => /aria|jenny|guy|google|natural|neural|samantha|daniel/i.test(String(v && v.name || ""))) || null;
          const utter = new SpeechSynthesisUtterance(text);
          utter.voice = preferred;
          utter.lang = preferred && preferred.lang ? preferred.lang : "en-US";
          utter.rate = Math.max(0.88, Math.min(1.03, Number(persona.rate || 1)));
          utter.pitch = Math.max(0.92, Math.min(1.06, Number(persona.pitch || 1)));
          utter.onend = () => resolve(true);
          utter.onerror = () => resolve(false);
          window.speechSynthesis.speak(utter);
        } catch (_) {
          resolve(false);
        }
      });
    }

    async function playAudioBlob(blob) {
      const url = URL.createObjectURL(blob);
      try {
        await new Promise((resolve, reject) => {
          const audio = new Audio(url);
          state.currentAudio = audio;
          audio.onended = () => resolve(true);
          audio.onerror = () => reject(new Error("audio_playback_failed"));
          const playResult = audio.play();
          if (playResult && typeof playResult.then === "function") {
            playResult.catch(reject);
          }
        });
      } finally {
        URL.revokeObjectURL(url);
        state.currentAudio = null;
      }
    }

    async function synthesizeChunk(chunk, personaName) {
      state.controller = new AbortController();
      const startedAt = Date.now();
      const res = await voiceApiFetch(apiBase + "/api/voice/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: state.controller.signal,
        body: JSON.stringify({ text: chunk, mode: personaName, preferred_provider: "openai_realtime_voice" }),
      });
      if (!res.ok) {
        throw new Error("voice_provider_unavailable");
      }
      const payload = await res.json();
      return {
        provider: payload && payload.provider ? payload.provider : "unknown",
        blob: base64ToBlob(payload.audio_b64, payload.mime_type),
        latencyMs: Math.max(0, Date.now() - startedAt),
      };
    }

    async function speak(rawText, options = {}) {
      const personaName = options.persona && PERSONAS[options.persona] ? options.persona : (state.lastPersona || "Warm Conversational");
      const persona = PERSONAS[personaName] || PERSONAS["Warm Conversational"];
      state.lastPersona = personaName;

      stop("speak-restart");
      state.interrupted = false;
      state.speaking = true;
      onState({ speaking: true, reason: "speak-start", persona: personaName });

      const cleaned = sanitizeForSpeech(rawText);
      state.resumeText = cleaned;
      const chunks = chunkTextForSpeech(cleaned, persona);
      state.queue = chunks;
      state.index = 0;

      const providers = await loadProviders();
      onDebug({ type: "voice-providers", providers });

      for (let i = state.index; i < state.queue.length; i += 1) {
        if (state.interrupted) break;
        state.index = i;
        const chunk = state.queue[i];

        try {
          let generated;
          try {
            generated = await synthesizeChunk(chunk, personaName);
          } catch (_) {
            generated = await synthesizeChunk(chunk, personaName);
          }
          if (state.interrupted) break;
          onDebug({
            type: "voice-chunk",
            index: i,
            provider: generated.provider,
            len: chunk.length,
            latencyMs: generated.latencyMs || 0,
            fallback: false,
            realtimeState: "provider",
          });
          await playAudioBlob(generated.blob);
        } catch (err) {
          onDebug({
            type: "voice-fallback",
            index: i,
            reason: String((err && err.message) || err),
            fallback: true,
            realtimeState: "fallback",
          });
          const ok = await fallbackBrowserSpeak(chunk, persona);
          if (!ok) {
            onDebug({ type: "voice-fallback-browser-failed", index: i });
            break;
          }
        }

        if (!state.interrupted && persona.pauseMs > 0) {
          await wait(persona.pauseMs);
        }
      }

      const interrupted = state.interrupted;
      state.speaking = false;
      onState({ speaking: false, reason: interrupted ? "interrupted" : "speak-complete", persona: personaName });
      return !interrupted;
    }

    async function resume() {
      if (!state.resumeText || state.speaking) return false;
      const personaName = state.lastPersona || "Warm Conversational";
      const persona = PERSONAS[personaName] || PERSONAS["Warm Conversational"];
      state.interrupted = false;
      state.speaking = true;
      onState({ speaking: true, reason: "resume", persona: personaName });

      for (let i = state.index; i < state.queue.length; i += 1) {
        if (state.interrupted) break;
        state.index = i;
        const chunk = state.queue[i];
        try {
          const generated = await synthesizeChunk(chunk, personaName);
          await playAudioBlob(generated.blob);
        } catch (_) {
          const ok = await fallbackBrowserSpeak(chunk, persona);
          if (!ok) break;
        }
        if (!state.interrupted && persona.pauseMs > 0) {
          await wait(persona.pauseMs);
        }
      }

      const interrupted = state.interrupted;
      state.speaking = false;
      onState({ speaking: false, reason: interrupted ? "interrupted" : "resume-complete", persona: personaName });
      return !interrupted;
    }

    return {
      speak,
      stop,
      resume,
      sanitizeForSpeech,
      personas: Object.keys(PERSONAS),
    };
  }

  window.AmiCorHumanVoice = {
    createEngine,
    sanitizeForSpeech,
    personas: Object.keys(PERSONAS),
  };
})();
