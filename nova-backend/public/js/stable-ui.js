(function (global) {
  'use strict';

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

  function connectStableSocket(handlers, refreshFn, options) {
    if (typeof io === 'undefined' || !refreshFn) return null;
    var opts = options || {};
    var minInterval = opts.minIntervalMs || 8000;
    var throttled = throttle(function () {
      if (document.hidden) return;
      try { refreshFn(); } catch (_) {}
    }, minInterval);
    var socket = io({ transports: ['websocket', 'polling'], reconnectionDelay: 5000 });
    Object.keys(handlers || {}).forEach(function (event) {
      if (event !== 'refresh') socket.on(event, handlers[event]);
    });
    socket.on('ops:update', throttled);
    return socket;
  }

  global.AmicorStable = {
    debounce: debounce,
    throttle: throttle,
    setHtmlIfChanged: setHtmlIfChanged,
    setTextIfChanged: setTextIfChanged,
    connectStableSocket: connectStableSocket,
  };
})();
