"use strict";

const { createSecurityError } = require("./pathSanitizer");

function validateCommand(command, allowlist) {
  const normalized = String(command || "").trim();
  const list = Array.isArray(allowlist) ? allowlist : [];

  if (!normalized) {
    throw createSecurityError("invalid-command", "A command is required");
  }
  if (list.length > 0 && list.indexOf(normalized) === -1) {
    throw createSecurityError("command-not-allowed", "Command is not allowlisted", {
      command: normalized,
      allowlist: list,
    });
  }

  return normalized;
}

function validateProcessArgs(args) {
  if (!Array.isArray(args)) {
    throw createSecurityError("invalid-args", "Process arguments must be an array");
  }

  args.forEach(function (arg, index) {
    if (typeof arg !== "string" && typeof arg !== "number" && typeof arg !== "boolean") {
      throw createSecurityError("invalid-arg", "Process arguments must be primitive values", {
        index: index,
        type: typeof arg,
      });
    }
  });

  return args.map(function (arg) { return String(arg); });
}

module.exports = {
  validateCommand: validateCommand,
  validateProcessArgs: validateProcessArgs,
};