/* ─── runtime/registry.js ────────────────────────────────────────────────
 * Tool registry: register, unregister, get, has, list.
 * Exposed on window._AmiCorRT.registry
 * ─────────────────────────────────────────────────────────────────────── */
(function (global) {
  "use strict";
  var ns = global._AmiCorRT = global._AmiCorRT || {};
  var errors = ns.errors || {};
  var ToolValidationError = errors.ToolValidationError || Error;

  function ToolRegistry() {
    this._tools = {};
  }

  ToolRegistry.prototype.register = function (name, definition) {
    if (!name || typeof name !== "string") {
      throw new ToolValidationError("Tool name must be a non-empty string");
    }
    if (!definition || typeof definition.handler !== "function") {
      throw new ToolValidationError("Tool definition must include a handler function: " + name);
    }
    if (this._tools[name]) {
      throw new ToolValidationError("Tool already registered: " + name);
    }
    this._tools[name] = {
      name        : name,
      description : definition.description || "",
      schema      : definition.schema || {},
      permissions : definition.permissions || [],
      handler     : definition.handler,
      timeout     : definition.timeout || 30000,
      retryable   : definition.retryable !== false,
      maxRetries  : definition.maxRetries || 0
    };
  };

  ToolRegistry.prototype.unregister = function (name) {
    if (!this._tools[name]) {
      throw new ToolValidationError("Tool not found: " + name);
    }
    delete this._tools[name];
  };

  ToolRegistry.prototype.get = function (name) {
    return this._tools[name] || null;
  };

  ToolRegistry.prototype.has = function (name) {
    return Object.prototype.hasOwnProperty.call(this._tools, name);
  };

  ToolRegistry.prototype.list = function () {
    var self = this;
    return Object.keys(this._tools).map(function (k) {
      var d = self._tools[k];
      return {
        name: d.name, description: d.description,
        schema: d.schema, permissions: d.permissions,
        timeout: d.timeout, retryable: d.retryable, maxRetries: d.maxRetries
      };
    });
  };

  ns.registry = { ToolRegistry: ToolRegistry };
})(window);
