"use strict";

(function (global) {
  function sanitizeUrl(url) {
    try {
      const parsed = new URL(String(url || "").trim(), global.location.origin);
      if (!/^https?:$/i.test(parsed.protocol)) return "";
      return parsed.toString();
    } catch (_) {
      return "";
    }
  }

  function createEmbeddedBrowser(options) {
    const config = Object.assign(
      {
        enabled: true,
        onEvent: null,
        mountRoot: null,
      },
      options || {}
    );

    const state = {
      open: false,
      currentUrl: "",
      currentTitle: "",
      history: [],
      historyIndex: -1,
      loading: false,
      blocked: false,
      lastError: null,
    };

    let elements = null;
    let loadTimeoutId = 0;

    function emit(type, payload) {
      if (typeof config.onEvent !== "function") return;
      try {
        config.onEvent(type, Object.assign({ source: "embedded-browser" }, payload || {}));
      } catch (_) {}
    }

    function ensureUi() {
      if (elements) return elements;

      const host = config.mountRoot || document.body;
      const shell = document.createElement("section");
      shell.id = "embedded-browser-shell";
      shell.hidden = true;
      shell.innerHTML =
        '<div class="embedded-browser-backdrop" data-eb="backdrop"></div>' +
        '<div class="embedded-browser-panel" role="dialog" aria-modal="true" aria-label="Embedded browser panel">' +
          '<div class="embedded-browser-toolbar">' +
            '<button type="button" class="embedded-browser-btn" data-eb="back" title="Back">Back</button>' +
            '<button type="button" class="embedded-browser-btn" data-eb="forward" title="Forward">Forward</button>' +
            '<button type="button" class="embedded-browser-btn" data-eb="refresh" title="Refresh">Refresh</button>' +
            '<div class="embedded-browser-title" data-eb="title">Embedded page</div>' +
            '<div class="embedded-browser-url" data-eb="url">about:blank</div>' +
            '<button type="button" class="embedded-browser-btn" data-eb="external" title="Open externally">Open externally</button>' +
            '<button type="button" class="embedded-browser-btn danger" data-eb="close" title="Close browser">Close</button>' +
          '</div>' +
          '<div class="embedded-browser-loading" data-eb="loading" hidden><span></span></div>' +
          '<div class="embedded-browser-status" data-eb="status">Ready.</div>' +
          '<iframe class="embedded-browser-frame" data-eb="frame" referrerpolicy="no-referrer" sandbox="allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-same-origin"></iframe>' +
          '<div class="embedded-browser-fallback" data-eb="fallback" hidden>' +
            '<p>This site does not allow embedded browsing here.</p>' +
            '<button type="button" class="embedded-browser-btn" data-eb="fallback-external">Open externally</button>' +
          '</div>' +
        '</div>';

      const style = document.createElement("style");
      style.id = "embedded-browser-style";
      style.textContent =
        '#embedded-browser-shell{position:fixed;inset:0;z-index:12000;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity 180ms ease}' +
        '#embedded-browser-shell[data-open="true"]{opacity:1}' +
        '.embedded-browser-backdrop{position:absolute;inset:0;background:rgba(4,6,12,.66)}' +
        '.embedded-browser-panel{position:relative;width:min(1100px,96vw);height:min(720px,90vh);background:#121522;border:1px solid rgba(255,255,255,.14);border-radius:12px;display:grid;grid-template-rows:auto auto auto 1fr;color:#e9edf9;overflow:hidden;transform:translateY(10px) scale(.985);transition:transform 180ms ease}' +
        '#embedded-browser-shell[data-open="true"] .embedded-browser-panel{transform:translateY(0) scale(1)}' +
        '.embedded-browser-toolbar{display:flex;align-items:center;gap:8px;padding:10px;border-bottom:1px solid rgba(255,255,255,.1)}' +
        '.embedded-browser-btn{border:1px solid rgba(255,255,255,.2);background:#1c2133;color:#e9edf9;border-radius:8px;min-height:30px;padding:0 10px;font-size:12px;font-weight:700;cursor:pointer}' +
        '.embedded-browser-btn:disabled{opacity:.45;cursor:not-allowed}' +
        '.embedded-browser-btn.danger{background:#7e2f43;border-color:#a94a63}' +
        '.embedded-browser-title{min-width:0;max-width:220px;font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#f4f6ff}' +
        '.embedded-browser-url{flex:1;min-width:0;font-size:12px;opacity:.86;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
        '.embedded-browser-loading{height:2px;background:rgba(255,255,255,.06);overflow:hidden}' +
        '.embedded-browser-loading span{display:block;width:32%;height:100%;background:linear-gradient(90deg,#8b85ff,#59b8ff);animation:embeddedBrowserLoad 1.2s ease-in-out infinite}' +
        '.embedded-browser-status{padding:7px 10px;font-size:12px;color:#b8c2e2;border-bottom:1px solid rgba(255,255,255,.08)}' +
        '.embedded-browser-frame{border:none;width:100%;height:100%;background:#0d1018}' +
        '.embedded-browser-fallback{position:absolute;inset:96px 14px 14px;border:1px dashed rgba(255,255,255,.24);border-radius:10px;background:rgba(9,12,20,.92);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:16px;text-align:center}' +
        '@media (max-width:720px){.embedded-browser-panel{width:min(100vw - 12px,1100px);height:min(100vh - 20px,720px);border-radius:10px}.embedded-browser-toolbar{flex-wrap:wrap;align-items:flex-start}.embedded-browser-title{order:10;max-width:100%;width:100%}.embedded-browser-url{order:11;width:100%;flex:1 1 100%}.embedded-browser-fallback{inset:136px 10px 10px}}' +
        '@keyframes embeddedBrowserLoad{0%{transform:translateX(-100%)}50%{transform:translateX(180%)}100%{transform:translateX(320%)}}';

      if (!document.getElementById(style.id)) {
        document.head.appendChild(style);
      }

      host.appendChild(shell);

      const by = (name) => shell.querySelector('[data-eb="' + name + '"]');
      const mapped = {
        shell,
        backdrop: by("backdrop"),
        back: by("back"),
        forward: by("forward"),
        refresh: by("refresh"),
        title: by("title"),
        url: by("url"),
        external: by("external"),
        close: by("close"),
        frame: by("frame"),
        loading: by("loading"),
        fallback: by("fallback"),
        fallbackExternal: by("fallback-external"),
        status: by("status"),
      };

      mapped.backdrop.addEventListener("click", () => close("backdrop"));
      mapped.close.addEventListener("click", () => close("close"));
      mapped.back.addEventListener("click", () => goBack());
      mapped.forward.addEventListener("click", () => goForward());
      mapped.refresh.addEventListener("click", () => refresh());
      mapped.external.addEventListener("click", () => openExternal());
      mapped.fallbackExternal.addEventListener("click", () => openExternal());

      mapped.frame.addEventListener("load", () => {
        state.loading = false;
        state.blocked = false;
        mapped.fallback.hidden = true;
        mapped.loading.hidden = true;
        mapped.status.textContent = "Loaded inside Amicor.";
        clearLoadTimeout();
        syncControls();
        emit("EMBEDDED_BROWSER_LOADED", { url: state.currentUrl });
      });

      mapped.frame.addEventListener("error", () => {
        handleBlocked("frame-error");
      });

      elements = mapped;
      return elements;
    }

    function clearLoadTimeout() {
      if (!loadTimeoutId) return;
      clearTimeout(loadTimeoutId);
      loadTimeoutId = 0;
    }

    function scheduleEmbedGuard() {
      clearLoadTimeout();
      loadTimeoutId = setTimeout(() => {
        if (!state.loading || !state.open) return;
        handleBlocked("embed-timeout");
      }, 8000);
    }

    function handleBlocked(reason) {
      const ui = ensureUi();
      state.loading = false;
      state.blocked = true;
      state.lastError = reason;
      ui.fallback.hidden = false;
      ui.loading.hidden = true;
      ui.status.textContent = "Embedding blocked by this site. Use Open externally.";
      syncControls();
      emit("EMBEDDED_BROWSER_BLOCKED", { url: state.currentUrl, reason });
    }

    function syncControls() {
      const ui = ensureUi();
      ui.back.disabled = state.historyIndex <= 0;
      ui.forward.disabled = state.historyIndex < 0 || state.historyIndex >= state.history.length - 1;
      ui.external.disabled = !state.currentUrl;
      ui.refresh.disabled = !state.currentUrl;
      ui.title.textContent = state.currentTitle || "Embedded page";
      ui.url.textContent = state.currentUrl || "about:blank";
      if (state.loading) {
        ui.status.textContent = "Loading page...";
        ui.loading.hidden = false;
      } else {
        ui.loading.hidden = true;
      }
    }

    function navigate(url, mode, metadata) {
      if (!config.enabled) {
        global.open(url, "_blank", "noopener,noreferrer");
        return false;
      }
      const safeUrl = sanitizeUrl(url);
      if (!safeUrl) return false;

      const ui = ensureUi();
      state.open = true;
      state.currentUrl = safeUrl;
      state.currentTitle = metadata && metadata.title ? String(metadata.title).trim().slice(0, 120) : state.currentTitle || safeUrl;
      state.blocked = false;
      state.lastError = null;
      state.loading = true;

      if (mode === "push") {
        const nextHistory = state.history.slice(0, state.historyIndex + 1);
        nextHistory.push(safeUrl);
        state.history = nextHistory.slice(-48);
        state.historyIndex = state.history.length - 1;
      }

      ui.fallback.hidden = true;
      ui.shell.hidden = false;
      ui.shell.dataset.open = "true";
      ui.frame.src = safeUrl;
      syncControls();
      scheduleEmbedGuard();

      emit("EMBEDDED_BROWSER_NAVIGATE", {
        url: safeUrl,
        mode,
        historyIndex: state.historyIndex,
        blocked: !!state.blocked,
        open: !!state.open,
      });
      return true;
    }

    function open(url) {
      var metadata = arguments.length > 1 ? arguments[1] : null;
      return navigate(url, "push", metadata);
    }

    function close(reason) {
      const ui = ensureUi();
      clearLoadTimeout();
      state.open = false;
      state.loading = false;
      ui.loading.hidden = true;
      ui.shell.dataset.open = "false";
      setTimeout(function () {
        if (!state.open) {
          ui.shell.hidden = true;
        }
      }, 180);
      emit("EMBEDDED_BROWSER_CLOSED", {
        reason: reason || "manual",
        url: state.currentUrl,
      });
    }

    function goBack() {
      if (state.historyIndex <= 0) return false;
      state.historyIndex -= 1;
      return navigate(state.history[state.historyIndex], "history-back", { title: state.currentTitle });
    }

    function goForward() {
      if (state.historyIndex < 0 || state.historyIndex >= state.history.length - 1) return false;
      state.historyIndex += 1;
      return navigate(state.history[state.historyIndex], "history-forward", { title: state.currentTitle });
    }

    function openExternal() {
      if (!state.currentUrl) return false;
      global.open(state.currentUrl, "_blank", "noopener,noreferrer");
      emit("EMBEDDED_BROWSER_OPEN_EXTERNAL", { url: state.currentUrl });
      return true;
    }

    function refresh() {
      if (!state.currentUrl) return false;
      const refreshed = navigate(state.currentUrl, "refresh", { title: state.currentTitle });
      if (refreshed) {
        emit("EMBEDDED_BROWSER_REFRESH", { url: state.currentUrl });
      }
      return refreshed;
    }

    function getSnapshot() {
      return Object.assign({}, state, {
        history: state.history.slice(),
      });
    }

    return {
      open,
      close,
      goBack,
      goForward,
      refresh,
      openExternal,
      getSnapshot,
    };
  }

  global.AmiCorEmbeddedBrowser = {
    createEmbeddedBrowser,
    sanitizeUrl,
  };
})(window);
