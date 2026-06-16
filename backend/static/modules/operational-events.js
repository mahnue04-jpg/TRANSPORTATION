(function () {
  "use strict";

  var listeners = [];
  var history = [];

  function nowIso() {
    return new Date().toISOString();
  }

  function emit(type, payload) {
    var event = {
      id: "evt-" + Date.now() + "-" + Math.floor(Math.random() * 100000),
      type: String(type || "event"),
      payload: payload || {},
      timestamp: nowIso()
    };
    history.unshift(event);
    history = history.slice(0, 500);
    listeners.slice().forEach(function (fn) {
      try {
        fn(event);
      } catch (_) {}
    });
    return event;
  }

  function onEvent(fn) {
    if (typeof fn !== "function") return function () {};
    listeners.push(fn);
    return function () {
      listeners = listeners.filter(function (item) { return item !== fn; });
    };
  }

  function getEvents(limit) {
    return history.slice(0, Math.max(1, Number(limit) || 200));
  }

  window.AmiOperationalEvents = {
    emit: emit,
    onEvent: onEvent,
    getEvents: getEvents
  };
})();
