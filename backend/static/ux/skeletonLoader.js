"use strict";
/**
 * skeletonLoader.js — Skeleton screen and loading state utilities for Amicor.
 *
 * Exposes: window.AmiCorSkeleton
 *
 * Features:
 *   - showPageSkeleton()   — Full-page skeleton while app initialises.
 *   - hidePageSkeleton()   — Remove page skeleton, reveal app.
 *   - createMessageSkeleton() — A single animated skeleton bubble (used while
 *                               a streaming response arrives).
 *   - showInputLock()      — Grey out + disable the input area during requests.
 *   - hideInputLock()      — Re-enable the input area.
 *   - shimmer CSS animation injected once on first call.
 */

;(function (global) {

  const PAGE_SKELETON_ID = "amicor-page-skeleton";

  // ── Styles ──────────────────────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById("amicor-skeleton-css")) return;
    const s = document.createElement("style");
    s.id = "amicor-skeleton-css";
    s.textContent = `
      /* Shimmer keyframe */
      @keyframes sk-shimmer {
        0%   { background-position: -400px 0; }
        100% { background-position:  400px 0; }
      }

      .sk-block {
        background: linear-gradient(90deg, #1c1c28 25%, #252535 50%, #1c1c28 75%);
        background-size: 800px 100%;
        animation: sk-shimmer 1.4s infinite linear;
        border-radius: 8px;
      }

      /* ── Page skeleton ── */
      #amicor-page-skeleton {
        position: fixed; inset: 0; z-index: 8000;
        background: #0b0b10;
        display: flex; flex-direction: column;
      }
      .sk-header {
        height: 58px; border-bottom: 1px solid #2a2a3e;
        display: flex; align-items: center; gap: 12px; padding: 0 16px;
        background: #13131c;
      }
      .sk-avatar   { width: 34px; height: 34px; border-radius: 10px; flex-shrink: 0; }
      .sk-title    { width: 90px; height: 14px; }
      .sk-subtitle { width: 60px; height: 10px; margin-top: 6px; }
      .sk-header-end { margin-left: auto; width: 80px; height: 28px; border-radius: 20px; }

      .sk-chip-bar {
        display: flex; gap: 6px; padding: 8px 16px;
        border-bottom: 1px solid #2a2a3e; background: #13131c;
      }
      .sk-chip-item { width: 72px; height: 24px; border-radius: 20px; }

      .sk-chat { flex: 1; padding: 20px 16px; display: flex; flex-direction: column; gap: 20px; }
      .sk-msg-ai   { display: flex; flex-direction: column; gap: 6px; max-width: 72%; align-self: flex-start; }
      .sk-msg-user { display: flex; flex-direction: column; gap: 6px; max-width: 60%; align-self: flex-end; }
      .sk-line     { height: 13px; }
      .sk-line-long   { width: 100%; }
      .sk-line-medium { width: 70%; }
      .sk-line-short  { width: 45%; }

      .sk-input {
        height: 72px; border-top: 1px solid #2a2a3e;
        background: #13131c; padding: 12px;
        display: flex; gap: 8px; align-items: flex-end;
      }
      .sk-input-box { flex: 1; height: 46px; border-radius: 16px; }
      .sk-btn       { width: 40px; height: 40px; border-radius: 12px; flex-shrink: 0; }

      /* ── Message skeleton bubble ── */
      .amicor-msg-skeleton {
        display: flex; flex-direction: column; gap: 7px;
        max-width: 72%; align-self: flex-start;
        padding: 11px 15px;
        background: #151520; border: 1px solid #2a2a3e;
        border-radius: 18px; border-bottom-left-radius: 5px;
      }
      .amicor-msg-skeleton .sk-line { border-radius: 6px; }

      /* ── Input lock overlay ── */
      #amicor-input-lock {
        position: absolute; inset: 0;
        background: rgba(11, 11, 16, 0.45);
        border-radius: inherit;
        z-index: 10;
        cursor: not-allowed;
      }
    `;
    document.head.appendChild(s);
  }

  // ── Page skeleton ────────────────────────────────────────────────────────────
  function buildPageSkeleton() {
    const root = document.createElement("div");
    root.id = PAGE_SKELETON_ID;

    root.innerHTML = `
      <div class="sk-header">
        <div class="sk-block sk-avatar"></div>
        <div>
          <div class="sk-block sk-title"></div>
          <div class="sk-block sk-subtitle"></div>
        </div>
        <div class="sk-block sk-header-end"></div>
      </div>
      <div class="sk-chip-bar">
        ${[72, 80, 68, 90, 76].map(w =>
          `<div class="sk-block sk-chip-item" style="width:${w}px"></div>`).join("")}
      </div>
      <div class="sk-chat">
        <div class="sk-msg-ai">
          <div class="sk-block sk-line sk-line-long"></div>
          <div class="sk-block sk-line sk-line-medium"></div>
          <div class="sk-block sk-line sk-line-short"></div>
        </div>
        <div class="sk-msg-user">
          <div class="sk-block sk-line sk-line-medium"></div>
          <div class="sk-block sk-line sk-line-short"></div>
        </div>
        <div class="sk-msg-ai">
          <div class="sk-block sk-line sk-line-long"></div>
          <div class="sk-block sk-line sk-line-long"></div>
          <div class="sk-block sk-line sk-line-medium"></div>
        </div>
      </div>
      <div class="sk-input">
        <div class="sk-block sk-input-box"></div>
        <div class="sk-block sk-btn"></div>
        <div class="sk-block sk-btn"></div>
      </div>
    `;
    return root;
  }

  // ── Message skeleton ─────────────────────────────────────────────────────────
  function createMessageSkeleton() {
    injectStyles();
    const wrap = document.createElement("div");
    wrap.className = "amicor-msg-skeleton";
    wrap.innerHTML = `
      <div class="sk-block sk-line" style="width:90%;height:12px;border-radius:6px"></div>
      <div class="sk-block sk-line" style="width:75%;height:12px;border-radius:6px"></div>
      <div class="sk-block sk-line" style="width:55%;height:12px;border-radius:6px"></div>
    `;
    return wrap;
  }

  // ── Input lock ───────────────────────────────────────────────────────────────
  let _lockEl = null;

  function showInputLock(inputWrapEl) {
    if (!inputWrapEl || _lockEl) return;
    injectStyles();
    const style = getComputedStyle(inputWrapEl).position;
    if (style === "static") inputWrapEl.style.position = "relative";
    _lockEl = document.createElement("div");
    _lockEl.id = "amicor-input-lock";
    inputWrapEl.appendChild(_lockEl);
  }

  function hideInputLock() {
    if (_lockEl) { _lockEl.remove(); _lockEl = null; }
  }

  // ── Public API ───────────────────────────────────────────────────────────────
  const AmiCorSkeleton = {
    showPageSkeleton() {
      injectStyles();
      if (document.getElementById(PAGE_SKELETON_ID)) return;
      const sk = buildPageSkeleton();
      document.body.insertBefore(sk, document.body.firstChild);
    },

    hidePageSkeleton({ animate = true } = {}) {
      const sk = document.getElementById(PAGE_SKELETON_ID);
      if (!sk) return;
      if (animate) {
        sk.style.transition = "opacity 0.3s";
        sk.style.opacity    = "0";
        setTimeout(() => sk.remove(), 320);
      } else {
        sk.remove();
      }
    },

    createMessageSkeleton,
    showInputLock,
    hideInputLock,
  };

  global.AmiCorSkeleton = AmiCorSkeleton;
  if (typeof module !== "undefined") module.exports = AmiCorSkeleton;

}(typeof window !== "undefined" ? window : global));
