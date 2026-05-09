/* ─── runtime/permissions.js ─────────────────────────────────────────────
 * Permission guard: checks required permissions against granted set.
 * Exposed on window._AmiCorRT.permissions
 * ─────────────────────────────────────────────────────────────────────── */
(function (global) {
  "use strict";
  var ns = global._AmiCorRT = global._AmiCorRT || {};

  function PermissionGuard() {}

  /* Returns { allowed: bool, missing: string[] } */
  PermissionGuard.prototype.check = function (required, granted) {
    required = required || [];
    granted  = granted  || [];
    var missing = required.filter(function (p) {
      return granted.indexOf(p) === -1;
    });
    return { allowed: missing.length === 0, missing: missing };
  };

  /* Singleton */
  var _guard = new PermissionGuard();

  ns.permissions = {
    PermissionGuard : PermissionGuard,
    check           : function (required, granted) { return _guard.check(required, granted); }
  };
})(window);
