"use strict";
/**
 * errorRecovery.js — UX error recovery utilities for Amicor.
 *
 * Exposes: window.AmiCorErrorRecovery
 *
 * Features:
 *   - addRetryButton(bubbleEl, retryFn)
 *       Appends a "Retry" button to a failed message bubble.
 *       Handles exponential back-off (1.5 s, 3 s, 6 s) up to MAX_RETRIES (3).
 *   - notify(message, level)
 *       Displays a transient toast notification (info | warn | error).
 *   - wrapFetch(fn, options)
 *       Wraps an async function with auto-retry + exponential backoff.
 *       Returns { data, error, attempts }.
 *   - trackError(context, err)
 *       Records errors to an in-memory ring buffer (last 50) for diagnostics.
 *   - getErrors()
 *       Returns the recorded error log.
 */

;(function (global) {

  const MAX_RETRIES  = 3;
  const BASE_DELAY   = 1500;   // ms
  const MAX_DELAY    = 10000;  // ms
  const TOAST_DURATION = 4000; // ms

  // ── Error ring buffer ────────────────────────────────────────────────────────
  const _errors = [];
  const ERROR_RING_SIZE = 50;

  function trackError(context, err) {
    _errors.push({
      context,
      message:   err && err.message ? err.message : String(err),
      timestamp: Date.now(),
    });
    if (_errors.length > ERROR_RING_SIZE) _errors.shift();
  }

  // ── Styles ──────────────────────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById("amicor-recovery-css")) return;
    const s = document.createElement("style");
    s.id = "amicor-recovery-css";
    s.textContent = `
      /* ── Retry button ── */
      .amicor-retry-btn {
        display: inline-flex; align-items: center; gap: 5px;
        margin-top: 8px;
        padding: 5px 12px; border-radius: 10px;
        border: 1px solid #2a2a3e; background: #1c1c28;
        color: #9494b8; font-size: 0.75rem; font-weight: 500;
        cursor: pointer; transition: all 0.15s;
      }
      .amicor-retry-btn:hover  { border-color: #6c63ff; color: #8b85ff; background: rgba(108,99,255,.08); }
      .amicor-retry-btn:active { transform: scale(0.94); }
      .amicor-retry-btn:disabled { opacity: 0.4; cursor: not-allowed; }
      .amicor-retry-btn .retry-count { color: #5c5c7e; font-size: 0.7rem; }

      /* ── Toast notifications ── */
      #amicor-toast-container {
        position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
        z-index: 9999; display: flex; flex-direction: column;
        align-items: center; gap: 8px; pointer-events: none;
      }
      .amicor-toast {
        padding: 10px 18px; border-radius: 12px;
        font-size: 0.82rem; font-weight: 500;
        box-shadow: 0 4px 20px rgba(0,0,0,0.4);
        animation: toast-in 0.2s ease;
        pointer-events: all; max-width: 340px; text-align: center;
      }
      @keyframes toast-in  { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
      @keyframes toast-out { from { opacity:1; } to { opacity:0; transform:translateY(-4px); } }
      .amicor-toast.info  { background: #1c1c28; border: 1px solid #2a2a3e; color: #9494b8; }
      .amicor-toast.warn  { background: #2a2010; border: 1px solid #f5a623; color: #f5a623; }
      .amicor-toast.error { background: #2a1015; border: 1px solid #ff5f72; color: #ff5f72; }
    `;
    document.head.appendChild(s);
  }

  // ── Toast ────────────────────────────────────────────────────────────────────
  let _toastContainer = null;

  function getToastContainer() {
    if (_toastContainer && _toastContainer.isConnected) return _toastContainer;
    _toastContainer = document.createElement("div");
    _toastContainer.id = "amicor-toast-container";
    document.body.appendChild(_toastContainer);
    return _toastContainer;
  }

  function notify(message, level = "info") {
    if (typeof document === "undefined") return;
    injectStyles();
    const container = getToastContainer();
    const toast = document.createElement("div");
    toast.className = "amicor-toast " + level;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.animation = "toast-out 0.2s ease forwards";
      setTimeout(() => toast.remove(), 220);
    }, TOAST_DURATION);
  }

  // ── Retry button ─────────────────────────────────────────────────────────────
  function addRetryButton(bubbleEl, retryFn) {
    if (!bubbleEl) return;
    injectStyles();

    // Remove any existing retry button on this bubble
    const existing = bubbleEl.querySelector(".amicor-retry-btn");
    if (existing) existing.remove();

    let attempts = 0;

    const btn = document.createElement("button");
    btn.className = "amicor-retry-btn";
    updateLabel();

    btn.addEventListener("click", async () => {
      if (attempts >= MAX_RETRIES) return;
      attempts++;
      btn.disabled = true;
      updateLabel();

      const delay = Math.min(BASE_DELAY * Math.pow(1.5, attempts - 1), MAX_DELAY);
      notify(`Retrying… (attempt ${attempts}/${MAX_RETRIES})`, "info");
      await new Promise(r => setTimeout(r, delay));

      try {
        await retryFn(attempts);
        // On success, remove the retry button
        btn.remove();
        notify("Retry succeeded", "info");
      } catch (err) {
        trackError("retryButton", err);
        btn.disabled = false;
        updateLabel();
        if (attempts >= MAX_RETRIES) {
          notify("Retry failed after " + MAX_RETRIES + " attempts", "error");
          btn.disabled = true;
        } else {
          notify(`Retry failed — ${MAX_RETRIES - attempts} attempt(s) left`, "warn");
        }
      }
    });

    bubbleEl.appendChild(btn);
    return btn;

    function updateLabel() {
      const left = MAX_RETRIES - attempts;
      btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
        <path d="M3 3v5h5"/></svg>
        Retry ${attempts > 0 ? `<span class="retry-count">(${left} left)</span>` : ""}`;
    }
  }

  // ── wrapFetch — auto-retry wrapper ──────────────────────────────────────────
  async function wrapFetch(fn, { retries = MAX_RETRIES, baseDelay = BASE_DELAY } = {}) {
    let lastErr;
    for (let i = 0; i <= retries; i++) {
      try {
        const data = await fn();
        return { data, error: null, attempts: i + 1 };
      } catch (err) {
        lastErr = err;
        trackError("wrapFetch", err);
        if (i < retries) {
          const delay = Math.min(baseDelay * Math.pow(1.5, i), MAX_DELAY);
          await new Promise(r => setTimeout(r, delay));
        }
      }
    }
    return { data: null, error: lastErr, attempts: retries + 1 };
  }

  // ── Public API ───────────────────────────────────────────────────────────────
  const AmiCorErrorRecovery = {
    addRetryButton,
    notify,
    wrapFetch,
    trackError,
    getErrors() { return [..._errors]; },
    clearErrors() { _errors.length = 0; },
    MAX_RETRIES,
  };

  global.AmiCorErrorRecovery = AmiCorErrorRecovery;
  if (typeof module !== "undefined") module.exports = AmiCorErrorRecovery;

}(typeof window !== "undefined" ? window : global));
