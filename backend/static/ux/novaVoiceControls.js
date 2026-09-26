"use strict";

(function () {
  var activeRecognition = null;
  var voiceEngine = null;
  var speakingFallback = false;
  var lastAutoSpokenText = "";
  var autoReadTimer = null;

  function voice() {
    if (!voiceEngine && window.AmiCorHumanVoice && window.AmiCorHumanVoice.createEngine) {
      voiceEngine = window.AmiCorHumanVoice.createEngine({ browserFallbackEnabled: true });
    }
    return voiceEngine;
  }

  function stopAll() {
    if (activeRecognition) {
      try { activeRecognition.abort(); } catch (_) {}
      activeRecognition = null;
    }
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
    var engine = voice();
    if (engine && engine.speak) {
      engine.speak(value, { persona: "Warm Conversational" }).catch(function () {});
      return;
    }
    if (!window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
      var utterance = new SpeechSynthesisUtterance(value);
      utterance.lang = "en-US";
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
    button.setAttribute("aria-label", "Read Nova answer aloud");
    button.textContent = "🎙 Read aloud";
    button.addEventListener("click", function () {
      lastAutoSpokenText = "";
      readBrainOutput("manual");
    });

    var stopButton = document.createElement("button");
    stopButton.type = "button";
    stopButton.className = "secondary";
    stopButton.setAttribute("data-nova-read-stop", "1");
    stopButton.setAttribute("aria-label", "Stop Nova reading");
    stopButton.textContent = "⏹ Stop";
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
    if (el) el.textContent = message;
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
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    setStatus(host, "Listening… speak now.");
    recognition.onresult = function (event) {
      var transcript = event.results && event.results[0] && event.results[0][0]
        ? event.results[0][0].transcript
        : "";
      input.value = transcript || "";
      setStatus(host, transcript ? "Heard: " + transcript : "Nothing heard. Try again.");
    };
    recognition.onerror = function (event) {
      var code = event && event.error ? event.error : "unavailable";
      setStatus(host, "Microphone error: " + code + ".");
    };
    recognition.onend = function () {
      if (activeRecognition === recognition) activeRecognition = null;
      if (input.value.trim()) setStatus(host, "Ready. Press Start Nova to run it.");
    };
    try { recognition.start(); }
    catch (_) { setStatus(host, "Microphone could not start. Check browser permission."); }
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
    talk.textContent = "🎤 Talk";
    talk.setAttribute("aria-label", "Talk to Nova");

    var start = document.createElement("button");
    start.type = "button";
    start.className = "secondary";
    start.textContent = "▶ Start Nova";
    start.setAttribute("aria-label", "Start Nova with this request");

    var stop = document.createElement("button");
    stop.type = "button";
    stop.className = "secondary";
    stop.textContent = "⏹ Stop";
    stop.setAttribute("aria-label", "Stop Nova voice");

    var status = document.createElement("span");
    status.className = "hint";
    status.setAttribute("data-nova-voice-status", "1");
    status.setAttribute("aria-live", "polite");
    status.textContent = "Voice ready.";

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
      startListening(input, form, host);
    });
    start.addEventListener("click", function () {
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
      speakNextChange(form);
      setStatus(host, "Running…");
      submitForm(form);
    });
    stop.addEventListener("click", function () {
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
    eligibleInputs().forEach(function (pair) {
      enhanceForm(pair[0], pair[1]);
    });
    installBrainAutoRead();
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
