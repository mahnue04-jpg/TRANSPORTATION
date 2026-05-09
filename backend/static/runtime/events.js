/* ─── runtime/events.js ──────────────────────────────────────────────────
 * EventBus + lifecycle HookSet for the tool runtime.
 * Exposed on window._AmiCorRT.events
 * ─────────────────────────────────────────────────────────────────────── */
(function (global) {
  "use strict";
  var ns = global._AmiCorRT = global._AmiCorRT || {};

  var TOOL_EVENTS = [
    "onStart","onChunk","onComplete","onCancel","onError","onRetry","onCleanup"
  ];

  /* ── EventBus ── */
  function EventBus() {
    this._listeners = {};
  }
  EventBus.prototype.on = function (event, fn) {
    if (!this._listeners[event]) { this._listeners[event] = []; }
    this._listeners[event].push(fn);
    var self = this, list = this._listeners[event];
    return { off: function () {
      var i = list.indexOf(fn);
      if (i !== -1) { list.splice(i, 1); }
    }};
  };
  EventBus.prototype.off = function (event, fn) {
    var list = this._listeners[event] || [];
    var i = list.indexOf(fn);
    if (i !== -1) { list.splice(i, 1); }
  };
  EventBus.prototype.emit = function (event, data) {
    var list = (this._listeners[event] || []).slice();
    list.forEach(function (fn) {
      try { fn(data); } catch (e) { /* isolate handler errors */ }
    });
  };
  EventBus.prototype.destroy = function () {
    this._listeners = {};
  };

  /* ── HookSet — one-time lifecycle hook registry ── */
  function HookSet() {
    this._hooks = {};
  }
  HookSet.prototype.add = function (name, fn) {
    if (!this._hooks[name]) { this._hooks[name] = []; }
    this._hooks[name].push(fn);
  };
  HookSet.prototype.fire = function (name, data) {
    var hooks = (this._hooks[name] || []).slice();
    hooks.forEach(function (fn) {
      try { fn(data); } catch (e) { /* isolate */ }
    });
  };
  HookSet.prototype.clear = function (name) {
    if (name) { this._hooks[name] = []; }
    else       { this._hooks = {}; }
  };

  ns.events = {
    TOOL_EVENTS : TOOL_EVENTS,
    EventBus    : EventBus,
    HookSet     : HookSet
  };
})(window);
