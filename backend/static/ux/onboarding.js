"use strict";
/**
 * onboarding.js — First-time user onboarding overlay for Amicor.
 *
 * Usage (index.html):
 *   AmiCorOnboarding.init({ onComplete: () => {} });
 *
 * Behaviour:
 *   - Reads localStorage key "amicor_onboarded" — skips overlay if set.
 *   - Renders a 3-step guided walkthrough as a modal overlay.
 *   - Each step has a title, description, and (optionally) a highlighted target.
 *   - "Skip" and "Done" both mark the user as onboarded and call onComplete.
 *   - Fully keyboard-accessible (Escape = skip, Enter = next).
 */

;(function (global) {

  const STORAGE_KEY = "amicor_onboarded";

  const STEPS = [
    {
      icon:  "🤖",
      title: "Welcome to Amicor",
      body:  "Your personal AI assistant for research, writing, news, and everyday tasks. Ask anything — Amicor adapts to you.",
    },
    {
      icon:  "💬",
      title: "Start a conversation",
      body:  "Type in the message box or tap the microphone to speak. Use the capability chips at the top to jump straight to weather, news, or a quick search.",
    },
    {
      icon:  "📎",
      title: "Attach files for context",
      body:  "Click the paperclip icon to upload text documents, PDFs, CSVs, or images. Amicor will read them and use them to give you smarter answers.",
    },
  ];

  // ── DOM helpers ─────────────────────────────────────────────────────────────

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "class") node.className = v;
      else if (k === "style") node.style.cssText = v;
      else node.setAttribute(k, v);
    });
    children.forEach(c => {
      if (typeof c === "string") node.appendChild(document.createTextNode(c));
      else if (c) node.appendChild(c);
    });
    return node;
  }

  function injectStyles() {
    if (document.getElementById("amicor-onboarding-css")) return;
    const style = document.createElement("style");
    style.id = "amicor-onboarding-css";
    style.textContent = `
      #amicor-onboarding-overlay {
        position: fixed; inset: 0; z-index: 9000;
        background: rgba(7, 7, 14, 0.82);
        backdrop-filter: blur(6px);
        display: flex; align-items: center; justify-content: center;
        padding: 24px;
        animation: ob-fade-in 0.25s ease;
      }
      @keyframes ob-fade-in { from { opacity: 0; } to { opacity: 1; } }

      #amicor-onboarding-card {
        background: #13131c;
        border: 1px solid #2a2a3e;
        border-radius: 20px;
        padding: 32px 28px 24px;
        max-width: 380px;
        width: 100%;
        text-align: center;
        box-shadow: 0 24px 60px rgba(0,0,0,0.6);
        animation: ob-slide-up 0.28s cubic-bezier(.34,1.56,.64,1);
      }
      @keyframes ob-slide-up {
        from { transform: translateY(24px); opacity: 0; }
        to   { transform: translateY(0);    opacity: 1; }
      }

      .ob-icon     { font-size: 2.8rem; margin-bottom: 14px; line-height: 1; }
      .ob-title    { font-size: 1.1rem; font-weight: 700; color: #e9e9f4; margin-bottom: 10px; }
      .ob-body     { font-size: 0.85rem; color: #9494b8; line-height: 1.6; margin-bottom: 24px; }

      .ob-dots     { display: flex; justify-content: center; gap: 6px; margin-bottom: 22px; }
      .ob-dot      { width: 7px; height: 7px; border-radius: 50%; background: #2a2a3e; transition: background 0.2s; }
      .ob-dot.active { background: #6c63ff; }

      .ob-actions  { display: flex; gap: 10px; justify-content: center; }
      .ob-btn-skip {
        padding: 9px 18px; border-radius: 12px;
        border: 1px solid #2a2a3e; background: transparent;
        color: #5c5c7e; font-size: 0.82rem; cursor: pointer;
        transition: all 0.15s;
      }
      .ob-btn-skip:hover { border-color: #353550; color: #9494b8; }
      .ob-btn-next {
        padding: 9px 22px; border-radius: 12px;
        border: none; background: #6c63ff;
        color: #fff; font-size: 0.82rem; font-weight: 600;
        cursor: pointer; transition: background 0.15s;
        flex: 1; max-width: 160px;
      }
      .ob-btn-next:hover { background: #8b85ff; }
    `;
    document.head.appendChild(style);
  }

  // ── Core ────────────────────────────────────────────────────────────────────

  function createOverlay(onDone) {
    let step = 0;

    const overlay = el("div", { id: "amicor-onboarding-overlay" });
    const card    = el("div", { id: "amicor-onboarding-card" });
    overlay.appendChild(card);

    const iconEl   = el("div", { class: "ob-icon" });
    const titleEl  = el("div", { class: "ob-title" });
    const bodyEl   = el("div", { class: "ob-body" });
    const dotsWrap = el("div", { class: "ob-dots" });
    const actions  = el("div", { class: "ob-actions" });
    const skipBtn  = el("button", { class: "ob-btn-skip" }, "Skip");
    const nextBtn  = el("button", { class: "ob-btn-next" }, "Next");

    // Build dots
    const dots = STEPS.map((_, i) => {
      const d = el("div", { class: "ob-dot" + (i === 0 ? " active" : "") });
      dotsWrap.appendChild(d);
      return d;
    });

    actions.appendChild(skipBtn);
    actions.appendChild(nextBtn);
    card.append(iconEl, titleEl, bodyEl, dotsWrap, actions);

    function render() {
      const s      = STEPS[step];
      iconEl.textContent  = s.icon;
      titleEl.textContent = s.title;
      bodyEl.textContent  = s.body;
      dots.forEach((d, i) => d.classList.toggle("active", i === step));
      nextBtn.textContent = step === STEPS.length - 1 ? "Get started" : "Next";
    }

    function complete() {
      try { localStorage.setItem(STORAGE_KEY, "1"); } catch (_) {}
      overlay.remove();
      onDone();
    }

    nextBtn.addEventListener("click", () => {
      step < STEPS.length - 1 ? (step++, render()) : complete();
    });
    skipBtn.addEventListener("click", complete);
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "Escape") complete();
      if (e.key === "Enter")  nextBtn.click();
    });
    // Close on backdrop click (not card click)
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) complete();
    });

    render();
    return overlay;
  }

  // ── Public API ───────────────────────────────────────────────────────────────

  const AmiCorOnboarding = {
    /**
     * init({ onComplete })
     *   onComplete — called when the user completes or skips onboarding.
     *   Shows the overlay only on first visit (localStorage flag).
     *   Pass force:true to always show regardless of stored flag.
     */
    init({ onComplete = () => {}, force = false } = {}) {
      injectStyles();
      let alreadyDone = false;
      try { alreadyDone = !!localStorage.getItem(STORAGE_KEY); } catch (_) {}
      if (alreadyDone && !force) { onComplete(); return; }

      const overlay = createOverlay(onComplete);
      (document.body || document.documentElement).appendChild(overlay);
      overlay.focus();
    },

    /** Reset the onboarding flag (useful in settings "Show intro again"). */
    reset() {
      try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
    },

    isCompleted() {
      try { return !!localStorage.getItem(STORAGE_KEY); } catch (_) { return false; }
    },
  };

  global.AmiCorOnboarding = AmiCorOnboarding;
  if (typeof module !== "undefined") module.exports = AmiCorOnboarding;

}(typeof window !== "undefined" ? window : global));
