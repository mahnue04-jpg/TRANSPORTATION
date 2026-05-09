"use strict";
/**
 * uploadUX.js — File upload UX for Amicor.
 *
 * Exposes: window.AmiCorUpload
 *
 * Features:
 *   - Click-to-upload (hidden <input type="file">)
 *   - Drag-and-drop onto the input area
 *   - Preview strip showing attached files
 *   - Per-file remove button
 *   - File type + size validation (max 10 MB, allowed MIME types)
 *   - Upload to /api/upload and inject extracted_text into message box
 *   - Retry on upload failure (up to 2 retries with 1.5s backoff)
 *   - Fully accessible: keyboard + screen-reader labels
 */

;(function (global) {

  const MAX_BYTES   = 10 * 1024 * 1024;   // 10 MB
  const MAX_RETRIES = 2;
  const RETRY_DELAY = 1500;               // ms

  const ALLOWED_TYPES = new Set([
    "text/plain", "text/markdown", "text/csv",
    "application/json", "application/pdf",
    "image/png", "image/jpeg", "image/webp",
  ]);

  const ICONS = {
    "text/":        "📄",
    "image/":       "🖼️",
    "application/json": "{ }",
    "application/pdf":  "📋",
    "default":      "📎",
  };

  function iconFor(type) {
    for (const [prefix, icon] of Object.entries(ICONS)) {
      if (type.startsWith(prefix)) return icon;
    }
    return ICONS.default;
  }

  function formatBytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(1) + " MB";
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // ── Styles ──────────────────────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById("amicor-upload-css")) return;
    const s = document.createElement("style");
    s.id = "amicor-upload-css";
    s.textContent = `
      #amicor-upload-strip {
        display: flex; gap: 8px; flex-wrap: wrap;
        padding: 0 12px 8px; min-height: 0;
      }
      .amicor-file-chip {
        display: inline-flex; align-items: center; gap: 6px;
        background: #1c1c28; border: 1px solid #2a2a3e;
        border-radius: 10px; padding: 5px 10px 5px 8px;
        font-size: 0.75rem; color: #9494b8;
        animation: chip-in 0.15s ease;
      }
      @keyframes chip-in { from { opacity:0; transform:scale(.92); } to { opacity:1; transform:scale(1); } }
      .amicor-file-chip .chip-icon   { font-size: 1rem; }
      .amicor-file-chip .chip-name   { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .amicor-file-chip .chip-size   { color: #5c5c7e; font-size: 0.68rem; }
      .amicor-file-chip .chip-remove {
        background: none; border: none; color: #5c5c7e;
        cursor: pointer; font-size: 1rem; line-height: 1;
        padding: 0 0 0 2px; transition: color 0.15s;
      }
      .amicor-file-chip .chip-remove:hover { color: #ff5f72; }
      .amicor-file-chip.uploading { border-color: #6c63ff; }
      .amicor-file-chip.error     { border-color: #ff5f72; color: #ff5f72; }
      .amicor-file-chip.done      { border-color: #43c98a; }

      /* Drag-over highlight on the input wrapper */
      .amicor-drag-over {
        border-color: #6c63ff !important;
        box-shadow: 0 0 0 3px rgba(108,99,255,0.25) !important;
      }

      #amicor-upload-btn {
        flex-shrink: 0;
        width: 40px; height: 40px; border-radius: 12px;
        border: none; background: #1c1c28;
        color: #5c5c7e; cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        transition: background 0.15s, color 0.15s, transform 0.1s;
      }
      #amicor-upload-btn:hover  { background: #252535; color: #9494b8; }
      #amicor-upload-btn:active { transform: scale(0.91); }
    `;
    document.head.appendChild(s);
  }

  // ── State ───────────────────────────────────────────────────────────────────
  let _attachments = [];     // { file, id, status, extractedText }
  let _stripEl     = null;
  let _inputEl     = null;   // the hidden <input type="file">
  let _dropZone    = null;
  let _onAttach    = null;   // callback(attachments)

  function nextId() {
    return "uf_" + Math.random().toString(36).slice(2, 9);
  }

  // ── Preview strip ────────────────────────────────────────────────────────────
  function renderStrip() {
    if (!_stripEl) return;
    _stripEl.innerHTML = "";
    _attachments.forEach(att => {
      const chip = document.createElement("div");
      chip.className = "amicor-file-chip " + att.status;
      chip.dataset.id = att.id;

      const icon   = document.createElement("span");
      icon.className = "chip-icon";
      icon.textContent = iconFor(att.file.type);

      const name = document.createElement("span");
      name.className = "chip-name";
      name.title = att.file.name;
      name.textContent = att.file.name;

      const size = document.createElement("span");
      size.className = "chip-size";
      size.textContent = att.status === "uploading" ? "uploading…"
                       : att.status === "error"     ? "failed"
                       : formatBytes(att.file.size);

      const rm = document.createElement("button");
      rm.className = "chip-remove";
      rm.title = "Remove file";
      rm.setAttribute("aria-label", "Remove " + att.file.name);
      rm.textContent = "×";
      rm.addEventListener("click", () => removeAttachment(att.id));

      chip.append(icon, name, size, rm);
      _stripEl.appendChild(chip);
    });
    if (_onAttach) _onAttach([..._attachments]);
  }

  function removeAttachment(id) {
    _attachments = _attachments.filter(a => a.id !== id);
    renderStrip();
  }

  // ── Validation ───────────────────────────────────────────────────────────────
  function validateFile(file) {
    if (file.size > MAX_BYTES) return `${file.name}: too large (max 10 MB)`;
    const mime = (file.type || "").split(";")[0].trim();
    if (!ALLOWED_TYPES.has(mime)) return `${file.name}: unsupported type (${mime || "unknown"})`;
    return null;
  }

  // ── Upload with retry ─────────────────────────────────────────────────────
  async function uploadWithRetry(att) {
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const form = new FormData();
        form.append("file", att.file);
        const res = await fetch("/api/upload", { method: "POST", body: form });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        att.status        = "done";
        att.extractedText = data.extracted_text || null;
        renderStrip();
        return;
      } catch (err) {
        if (attempt < MAX_RETRIES) {
          await sleep(RETRY_DELAY * (attempt + 1));
        } else {
          att.status = "error";
          att.error  = err.message;
          renderStrip();
        }
      }
    }
  }

  // ── File handling ─────────────────────────────────────────────────────────
  async function handleFiles(fileList) {
    const files = Array.from(fileList);
    for (const file of files) {
      const err = validateFile(file);
      if (err) {
        // Surface validation error — delegate to AmiCorErrorRecovery if available
        if (global.AmiCorErrorRecovery) {
          global.AmiCorErrorRecovery.notify(err, "warn");
        } else {
          console.warn("[UploadUX]", err);
        }
        continue;
      }
      const att = { file, id: nextId(), status: "uploading", extractedText: null };
      _attachments.push(att);
      renderStrip();
      uploadWithRetry(att); // fire-and-forget; renderStrip() called on completion
    }
  }

  // ── Drag-and-drop ─────────────────────────────────────────────────────────
  function setupDropZone(el) {
    _dropZone = el;
    el.addEventListener("dragover",  (e) => { e.preventDefault(); el.classList.add("amicor-drag-over"); });
    el.addEventListener("dragleave", ()  => el.classList.remove("amicor-drag-over"));
    el.addEventListener("drop",      (e) => {
      e.preventDefault();
      el.classList.remove("amicor-drag-over");
      handleFiles(e.dataTransfer.files);
    });
  }

  // ── Public API ───────────────────────────────────────────────────────────────
  const AmiCorUpload = {
    /**
     * init({ stripContainer, dropZoneEl, onAttach })
     *   stripContainer — Element to render the file-chip preview strip into.
     *   dropZoneEl     — Element that accepts drag-and-drop (e.g. the input box).
     *   onAttach(list) — Called whenever the attachments list changes.
     *
     * Returns the upload-trigger button element (caller appends it to the toolbar).
     */
    init({ stripContainer, dropZoneEl, onAttach } = {}) {
      injectStyles();

      _stripEl  = stripContainer || null;
      _onAttach = onAttach       || null;
      if (dropZoneEl) setupDropZone(dropZoneEl);

      // Hidden file input
      _inputEl = document.createElement("input");
      _inputEl.type     = "file";
      _inputEl.multiple = true;
      _inputEl.accept   = Array.from(ALLOWED_TYPES).join(",");
      _inputEl.style.display = "none";
      _inputEl.setAttribute("aria-label", "Upload file");
      _inputEl.addEventListener("change", () => {
        if (_inputEl.files && _inputEl.files.length) {
          handleFiles(_inputEl.files);
          _inputEl.value = ""; // allow re-selecting the same file
        }
      });
      document.body.appendChild(_inputEl);

      // Upload button
      const btn = document.createElement("button");
      btn.id        = "amicor-upload-btn";
      btn.title     = "Attach file";
      btn.setAttribute("aria-label", "Attach file");
      btn.innerHTML = `<svg width="17" height="17" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.41 17.41a2 2 0 0 1-2.83-2.83L15.07 6.1"/>
      </svg>`;
      btn.addEventListener("click", () => _inputEl.click());
      return btn;
    },

    /** Return copies of current attachments (status, extractedText). */
    getAttachments() { return [..._attachments]; },

    /** Return concatenated extracted text from all successfully uploaded files. */
    getExtractedContext() {
      return _attachments
        .filter(a => a.status === "done" && a.extractedText)
        .map(a => `[File: ${a.file.name}]\n${a.extractedText}`)
        .join("\n\n");
    },

    /** Clear all attachments and re-render. */
    clear() {
      _attachments = [];
      renderStrip();
    },
  };

  global.AmiCorUpload = AmiCorUpload;
  if (typeof module !== "undefined") module.exports = AmiCorUpload;

}(typeof window !== "undefined" ? window : global));
