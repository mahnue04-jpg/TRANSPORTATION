"use strict";

(function () {
  var params = new URLSearchParams(window.location.search || "");
  var demoEmbed = params.get("nova_demo_embed") === "1";
  var activeRecognition = null;
  var listeningRequested = false;
  var restartTimer = null;
  var voiceEngine = null;
  var speakingFallback = false;
  var lastAutoSpokenText = "";
  var autoReadTimer = null;
  function t(message) { return window.NovaWorkspaceLanguage ? window.NovaWorkspaceLanguage.t(message) : message; }
  function selectedLanguage() { return document.documentElement.getAttribute("data-nova-language") || "en-US"; }
  function unavailableVoice() {
    var notice = document.getElementById("language-help");
    if (notice) notice.textContent = "Voice output is unavailable for this request. You can continue using Somali text or choose English audio.";
  }

  function voice() {
    if (!voiceEngine && window.AmiCorHumanVoice && window.AmiCorHumanVoice.createEngine) {
      voiceEngine = window.AmiCorHumanVoice.createEngine({ browserFallbackEnabled: true, getLanguage: selectedLanguage });
    }
    return voiceEngine;
  }

  function stopAll() {
    listeningRequested = false;
    window.clearTimeout(restartTimer);
    if (activeRecognition) {
      try { activeRecognition.abort(); } catch (_) {}
      activeRecognition = null;
    }
    if (window.NovaWorkspaceSpeech) window.NovaWorkspaceSpeech.stop();
    var engine = voice();
    if (engine && engine.stop) {
      try { engine.stop("universal-stop"); } catch (_) {}
    }
    if (window.speechSynthesis) {
      try { window.speechSynthesis.cancel(); } catch (_) {}
    }
    speakingFallback = false;
  }

  function speak(text) {
    var value = String(text || "").trim();
    if (!value) return;
    if (window.NovaWorkspaceSpeech) { window.NovaWorkspaceSpeech.speak(value); return; }
    var engine = voice();
    if (engine && engine.speak) {
      engine.speak(value, { persona: "Warm Conversational" }).then(function (ok) { if (ok === false) unavailableVoice(); }).catch(unavailableVoice);
      return;
    }
    if (!window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
      var utterance = new SpeechSynthesisUtterance(value);
      utterance.lang = selectedLanguage();
      if (/^so/i.test(utterance.lang)) {
        var somali = window.speechSynthesis.getVoices().find(function (item) { return /^so(?:-|$)/i.test(item.lang); });
        if (!somali) { unavailableVoice(); return; }
        utterance.voice = somali;
      }
      speakingFallback = true;
      utterance.onend = function () { speakingFallback = false; };
      window.speechSynthesis.speak(utterance);
    } catch (_) {}
  }

  function readBrainOutput(reason) {
    var target = document.getElementById("brain-output");
    var value = target ? String(target.textContent || "").trim() : "";
    if (!value || value === lastAutoSpokenText) return false;
    lastAutoSpokenText = value;
    speak(value);
    return true;
  }

  function installBrainAutoRead() {
    var target = document.getElementById("brain-output");
    if (!target || target.dataset.novaAutoReadReady === "1" || !window.MutationObserver) return;
    target.dataset.novaAutoReadReady = "1";
    var observer = new MutationObserver(function () {
      window.clearTimeout(autoReadTimer);
      autoReadTimer = window.setTimeout(function () {
        readBrainOutput("result-change");
      }, 180);
    });
    observer.observe(target, { childList: true, subtree: true, characterData: true });
  }

  function installReadResultButton() {
    var target = document.getElementById("brain-output");
    if (!target || document.querySelector("[data-nova-read-result]")) return;
    var button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.setAttribute("data-nova-read-result", "1");
    button.setAttribute("data-nova-label", "Read Nova answer aloud");
    button.setAttribute("aria-label", t("Read Nova answer aloud"));
    button.setAttribute("data-nova-i18n", "🎙 Read aloud");
    button.textContent = t("🎙 Read aloud");
    button.addEventListener("click", function () {
      lastAutoSpokenText = "";
      readBrainOutput("manual");
    });

    var stopButton = document.createElement("button");
    stopButton.type = "button";
    stopButton.className = "secondary";
    stopButton.setAttribute("data-nova-read-stop", "1");
    stopButton.setAttribute("data-nova-label", "Stop Nova reading");
    stopButton.setAttribute("aria-label", t("Stop Nova reading"));
    stopButton.setAttribute("data-nova-i18n", "⏹ Stop");
    stopButton.textContent = t("⏹ Stop");
    stopButton.addEventListener("click", function () {
      stopAll();
    });

    var controls = document.createElement("div");
    controls.className = "command-actions nova-read-controls";
    controls.appendChild(button);
    controls.appendChild(stopButton);
    target.insertAdjacentElement("afterend", controls);
  }

  function setStatus(host, message) {
    var el = host.querySelector("[data-nova-voice-status]");
    if (el) el.textContent = t(message);
  }

  function submitForm(form) {
    if (!form) return;
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  }

  function resultTarget(form) {
    if (!form) return null;
    if (form.id === "search-form") return document.getElementById("search-results");
    if (form.id === "workspace-search-form") return document.getElementById("search-results");
    if (form.id === "contact-search-form") return document.getElementById("contact-list");
    if (form.id === "command-form") return document.getElementById("brain-output") || document.getElementById("search-results");
    return document.getElementById("brain-output");
  }

  function speakNextChange(form) {
    var target = resultTarget(form);
    if (!target || !window.MutationObserver) return;
    var done = false;
    var observer = new MutationObserver(function () {
      if (done) return;
      var text = String(target.textContent || "").trim();
      if (!text) return;
      done = true;
      observer.disconnect();
      window.setTimeout(function () { speak(text); }, 100);
    });
    observer.observe(target, { childList: true, subtree: true, characterData: true });
    window.setTimeout(function () {
      if (!done) observer.disconnect();
    }, 15000);
  }

  function startListening(input, form, host) {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setStatus(host, "Voice input is not supported in this browser.");
      return;
    }
    stopAll();
    var recognition = new SR();
    activeRecognition = recognition;
    recognition.lang = selectedLanguage();
    recognition.interimResults = false;
    recognition.continuous = true;
    listeningRequested = true;
    recognition.maxAlternatives = 1;
    setStatus(host, "Listening… speak now.");
    recognition.onresult = function (event) {
      var words = [];
      for (var i = event.resultIndex || 0; i < event.results.length; i++) {
        if (event.results[i].isFinal && event.results[i][0]) words.push(event.results[i][0].transcript);
      }
      if (words.length) input.value = (input.value ? input.value + " " : "") + words.join(" ");
      setStatus(host, "Listening through pauses. Press Stop when done, review the text, then Ask Nova.");
    };
    recognition.onerror = function (event) {
      var code = event && event.error ? event.error : "unavailable";
      if (code === "no-speech") return;
      listeningRequested = false;
      setStatus(host, "Microphone error: " + code + ". Your text remains available.");
    };
    recognition.onend = function () {
      if (activeRecognition !== recognition) return;
      if (listeningRequested) {
        restartTimer = window.setTimeout(function () {
          if (!listeningRequested || activeRecognition !== recognition) return;
          try { recognition.start(); }
          catch (_) { listeningRequested = false; activeRecognition = null; setStatus(host, "Microphone stopped. Your text remains available."); }
        }, 250);
      } else {
        activeRecognition = null;
        setStatus(host, "Review your words, then press Ask Nova.");
      }
    };
    try { recognition.start(); }
    catch (_) { listeningRequested = false; activeRecognition = null; setStatus(host, "Microphone could not start. Check browser permission."); }
  }

  function enhanceForm(form, input) {
    if (!form || !input || form.dataset.novaVoiceReady === "1") return;
    if (form.querySelector("#ask-mic")) return;
    form.dataset.novaVoiceReady = "1";

    var host = document.createElement("div");
    host.className = "command-actions nova-voice-controls";
    host.setAttribute("data-nova-voice-controls", "1");

    var talk = document.createElement("button");
    talk.type = "button";
    talk.className = "secondary";
    talk.setAttribute("data-nova-i18n", "🎤 Talk");
    talk.textContent = t("🎤 Talk");
    talk.setAttribute("data-nova-label", "Talk to Nova");
    talk.setAttribute("aria-label", t("Talk to Nova"));

    var start = document.createElement("button");
    start.type = "button";
    start.className = "secondary";
    start.setAttribute("data-nova-i18n", "▶ Start Nova");
    start.textContent = t("▶ Start Nova");
    start.setAttribute("data-nova-label", "Start Nova with this request");
    start.setAttribute("aria-label", t("Start Nova with this request"));

    var stop = document.createElement("button");
    stop.type = "button";
    stop.className = "secondary";
    stop.setAttribute("data-nova-i18n", "⏹ Stop");
    stop.textContent = t("⏹ Stop");
    stop.setAttribute("data-nova-label", "Stop Nova voice");
    stop.setAttribute("aria-label", t("Stop Nova voice"));

    var status = document.createElement("span");
    status.className = "hint";
    status.setAttribute("data-nova-voice-status", "1");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("data-nova-i18n", "Voice ready.");
    status.textContent = t("Voice ready.");

    host.appendChild(talk);
    host.appendChild(start);
    host.appendChild(stop);
    host.appendChild(status);

    var submitButton = form.querySelector('button[type="submit"]');
    if (submitButton && submitButton.parentNode === form) {
      submitButton.insertAdjacentElement("afterend", host);
    } else {
      form.appendChild(host);
    }

    talk.addEventListener("click", function () {
      if (window.NovaWorkspaceSpeech && form.id === "ask-form") document.getElementById("record-somali").click();
      else startListening(input, form, host);
    });
    start.addEventListener("click", function () {
      if (window.NovaWorkspaceRecording && window.NovaWorkspaceRecording.isBusy()) { setStatus(host, "Finish recording and review your words before asking Nova."); return; }
      if (!String(input.value || "").trim()) {
        var target = resultTarget(form);
        if (target && String(target.textContent || "").trim()) {
          speak(target.textContent);
          setStatus(host, "Reading the current Nova result.");
          return;
        }
        setStatus(host, "Say or type something first.");
        return;
      }
      stopAll();
      if (!window.NovaWorkspaceSpeech) speakNextChange(form);
      setStatus(host, "Running…");
      submitForm(form);
    });
    stop.addEventListener("click", function () {
      if (window.NovaWorkspaceRecording) window.NovaWorkspaceRecording.finish();
      stopAll();
      setStatus(host, "Stopped.");
    });
  }

  function eligibleInputs() {
    var found = [];
    document.querySelectorAll("form").forEach(function (form) {
      if (form.id !== "ask-form" && form.id !== "command-form") return;
      var input = form.querySelector("#ask-input, #command-input");
      if (!input) return;
      found.push([form, input]);
    });
    return found;
  }

  function init() {
    if (demoEmbed) {
      if (window.speechSynthesis) {
        try { window.speechSynthesis.cancel(); } catch (_) {}
      }
      document.documentElement.setAttribute("data-nova-demo-voice-muted", "1");
      return;
    }
    eligibleInputs().forEach(function (pair) {
      enhanceForm(pair[0], pair[1]);
    });
    if (!window.NovaWorkspaceSpeech) installBrainAutoRead();
    installReadResultButton();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.AmiCorNovaVoiceControls = {
    init: init,
    stop: stopAll,
    speak: speak
  };
})();
