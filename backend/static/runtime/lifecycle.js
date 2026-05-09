/* ─── runtime/lifecycle.js ───────────────────────────────────────────────
 * Strict state-machine for tool execution lifecycle.
 * Exposed on window._AmiCorRT.lifecycle
 * ─────────────────────────────────────────────────────────────────────── */
(function (global) {
  "use strict";
  var ns = global._AmiCorRT = global._AmiCorRT || {};

  var STATES = {
    PENDING   : "pending",
    RUNNING   : "running",
    STREAMING : "streaming",
    RETRYING  : "retrying",
    COMPLETED : "completed",
    CANCELLED : "cancelled",
    TIMEOUT   : "timeout",
    FAILED    : "failed"
  };

  /* Terminal states accept no further transitions. */
  var TERMINAL = ["completed", "cancelled", "timeout", "failed"];

  /* Valid transitions — plain object to avoid ES6 computed-property syntax. */
  var TRANSITIONS = {};
  TRANSITIONS["pending"]   = ["running",  "cancelled"];
  TRANSITIONS["running"]   = ["streaming","completed","cancelled","timeout","failed","retrying"];
  TRANSITIONS["streaming"] = ["running",  "completed","cancelled","timeout","failed"];
  TRANSITIONS["retrying"]  = ["running",  "cancelled","failed"];
  TRANSITIONS["completed"] = [];
  TRANSITIONS["cancelled"] = [];
  TRANSITIONS["timeout"]   = [];
  TRANSITIONS["failed"]    = [];

  function canTransition(from, to) {
    var allowed = TRANSITIONS[from];
    return allowed ? allowed.indexOf(to) !== -1 : false;
  }

  function assertTransition(from, to) {
    if (!canTransition(from, to)) {
      throw new Error("Invalid lifecycle transition: " + from + " -> " + to);
    }
  }

  function isTerminal(state) {
    return TERMINAL.indexOf(state) !== -1;
  }

  ns.lifecycle = {
    STATES          : STATES,
    TRANSITIONS     : TRANSITIONS,
    TERMINAL        : TERMINAL,
    canTransition   : canTransition,
    assertTransition: assertTransition,
    isTerminal      : isTerminal
  };
})(window);
