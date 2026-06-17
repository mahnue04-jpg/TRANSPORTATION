(function (global) {
  'use strict';

  var POLL_MS = 30000;

  function debounce(fn, waitMs) {
    var timer = null;
    return function () {
      var ctx = this;
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(ctx, args); }, waitMs);
    };
  }

  function throttle(fn, waitMs) {
    var last = 0;
    var timer = null;
    return function () {
      var ctx = this;
      var args = arguments;
      var now = Date.now();
      var remaining = waitMs - (now - last);
      if (remaining <= 0) {
        last = now;
        fn.apply(ctx, args);
      } else if (!timer) {
        timer = setTimeout(function () {
          timer = null;
          last = Date.now();
          fn.apply(ctx, args);
        }, remaining);
      }
    };
  }

  function setHtmlIfChanged(el, html) {
    if (!el) return false;
    if (el.__stableHtml === html) return false;
    el.__stableHtml = html;
    el.innerHTML = html;
    return true;
  }

  function setTextIfChanged(el, text) {
    if (!el) return false;
    if (el.__stableText === text) return false;
    el.__stableText = text;
    el.textContent = text;
    return true;
  }

  /** HTTP polling only — no Socket.IO, no EventSource */
  function startPolling(fn, intervalMs) {
    var ms = intervalMs || POLL_MS;
    var tick = throttle(function () {
      if (!document.hidden) {
        try { fn(); } catch (_) {}
      }
    }, ms);
    setInterval(tick, ms);
    return tick;
  }

  global.AmicorStable = {
    POLL_MS: POLL_MS,
    debounce: debounce,
    throttle: throttle,
    setHtmlIfChanged: setHtmlIfChanged,
    setTextIfChanged: setTextIfChanged,
    startPolling: startPolling,
  };
})();
