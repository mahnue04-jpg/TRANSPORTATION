"use strict";

const path = require("path");

function createSecurityError(code, message, details) {
  const error = new Error(message);
  error.name = "ToolSecurityError";
  error.code = code;
  error.details = details || {};
  error.toJSON = function () {
    return { name: error.name, code: error.code, message: error.message, details: error.details };
  };
  return error;
}

function isPathInside(rootPath, candidatePath) {
  const relative = path.relative(rootPath, candidatePath);
  return !!relative && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function sanitizeSandboxPath(rootDir, inputPath, options) {
  const opts = options || {};
  if (!rootDir) {
    throw createSecurityError("invalid-root", "A sandbox root directory is required");
  }
  if (inputPath === undefined || inputPath === null) {
    throw createSecurityError("invalid-path", "A file path is required");
  }

  const rootPath = path.resolve(rootDir);
  const candidate = String(inputPath).replace(/\0/g, "").trim();
  const resolved = path.resolve(rootPath, candidate || ".");

  if (opts.allowRoot !== true && resolved === rootPath) {
    throw createSecurityError("invalid-path", "The sandbox root itself is not a valid target path");
  }
  if (!resolved.startsWith(rootPath) && !isPathInside(rootPath, resolved)) {
    throw createSecurityError("path-traversal", "Path escapes the sandbox root", { inputPath: candidate });
  }
  return resolved;
}

function assertAllowedExtension(filePath, allowlist) {
  const list = Array.isArray(allowlist) ? allowlist : [];
  if (list.length === 0) {
    return true;
  }
  const ext = path.extname(filePath).toLowerCase();
  const allowed = list.some(function (item) {
    const normalized = String(item || "").toLowerCase();
    return normalized === ext || normalized === ext.replace(/^\./, "") || normalized === "*";
  });
  if (!allowed) {
    throw createSecurityError("extension-not-allowed", "File extension is not allowlisted", {
      filePath: filePath,
      extension: ext,
      allowlist: list,
    });
  }
  return true;
}

module.exports = {
  createSecurityError: createSecurityError,
  sanitizeSandboxPath: sanitizeSandboxPath,
  assertAllowedExtension: assertAllowedExtension,
  isPathInside: isPathInside,
};