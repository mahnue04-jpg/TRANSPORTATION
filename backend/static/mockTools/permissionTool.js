/**
 * mockPermissionTool — Requires specific permissions
 * Usage: { level: "admin" | "user" | "guest" }
 */

(function (global) {
  "use strict";

  global.AmiCorMockTools = global.AmiCorMockTools || {};

  global.AmiCorMockTools.permissionTool = {
    name: "mock-permission",
    description: "Requires specific permissions based on access level",
    schema: {
      level: { type: "string", required: true, enum: ["admin", "user", "guest"] }
    },
    permissions: ["admin"], // Default required permission
    timeout: 5000,
    retryable: false,
    execute: function (args, ctx) {
      var level = args.level || "user";
      var accessGranted = false;

      if (level === "admin" && ctx.hasPermission("admin")) {
        accessGranted = true;
      } else if ((level === "user" || level === "admin") && ctx.hasPermission("user")) {
        accessGranted = true;
      } else if (level === "guest") {
        accessGranted = true; // guest always allowed
      }

      if (!accessGranted) {
        return Promise.reject(new Error("Permission denied for level: " + level));
      }

      return Promise.resolve({
        accessGranted: true,
        level: level,
        message: "Access granted at level: " + level
      });
    }
  };
})(typeof global !== "undefined" ? global : globalThis);
