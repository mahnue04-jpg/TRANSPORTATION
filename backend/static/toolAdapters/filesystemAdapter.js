"use strict";

const fs = require("fs/promises");
const path = require("path");

const {
  sanitizeSandboxPath,
  assertAllowedExtension,
  ensurePermissions,
  ensureWithinLimit,
  estimateSize,
} = require("../toolSecurity");

const { createToolError, chunkText } = require("./baseAdapter");

function createFilesystemAdapter(options) {
  const config = Object.assign(
    {
      rootDir: path.resolve(process.cwd(), "backend/static/.real-tool-sandbox"),
      allowedExtensions: [".txt", ".md", ".json"],
      maxFileSize: 1024 * 1024,
      maxChunkSize: 4096,
    },
    options || {}
  );

  async function ensureRoot() {
    await fs.mkdir(config.rootDir, { recursive: true });
  }

  function resolveTarget(inputPath, allowRoot) {
    return sanitizeSandboxPath(config.rootDir, inputPath, { allowRoot: !!allowRoot });
  }

  async function readFile(args, ctx) {
    ensurePermissions(["filesystem:read"], ctx && ctx.permissions, "filesystemTool");
    await ensureRoot();
    const targetPath = resolveTarget(args.path);
    assertAllowedExtension(targetPath, config.allowedExtensions);
    const stat = await fs.stat(targetPath).catch(function () {
      throw createToolError("file-not-found", "File not found", { path: targetPath });
    });
    ensureWithinLimit(stat.size, config.maxFileSize, "File size");
    const content = await fs.readFile(targetPath, "utf8");
    if (ctx && typeof ctx.emitChunk === "function") {
      chunkText(content, args.chunkSize || config.maxChunkSize).forEach(function (chunk) {
        ctx.emitChunk(chunk);
      });
    }
    return {
      path: targetPath,
      bytes: estimateSize(content),
      content: content,
    };
  }

  async function writeFile(args, ctx) {
    ensurePermissions(["filesystem:write"], ctx && ctx.permissions, "filesystemTool");
    await ensureRoot();
    const targetPath = resolveTarget(args.path);
    assertAllowedExtension(targetPath, config.allowedExtensions);
    const content = String(args.content || "");
    ensureWithinLimit(estimateSize(content), config.maxFileSize, "File content");
    await fs.mkdir(path.dirname(targetPath), { recursive: true });
    await fs.writeFile(targetPath, content, "utf8");
    return { path: targetPath, bytes: estimateSize(content), written: true };
  }

  async function appendFile(args, ctx) {
    ensurePermissions(["filesystem:write"], ctx && ctx.permissions, "filesystemTool");
    await ensureRoot();
    const targetPath = resolveTarget(args.path);
    assertAllowedExtension(targetPath, config.allowedExtensions);
    const addition = String(args.content || "");
    const existing = await fs.readFile(targetPath, "utf8").catch(function () {
      return "";
    });
    const merged = existing + addition;
    ensureWithinLimit(estimateSize(merged), config.maxFileSize, "File content");
    await fs.mkdir(path.dirname(targetPath), { recursive: true });
    await fs.writeFile(targetPath, merged, "utf8");
    return { path: targetPath, bytes: estimateSize(merged), appended: true };
  }

  async function listDirectory(args, ctx) {
    ensurePermissions(["filesystem:read"], ctx && ctx.permissions, "filesystemTool");
    await ensureRoot();
    const targetPath = resolveTarget(args.path || ".", true);
    const entries = await fs.readdir(targetPath, { withFileTypes: true });
    const mapped = [];
    for (const entry of entries) {
      const entryPath = path.join(targetPath, entry.name);
      const stat = await fs.stat(entryPath).catch(function () {
        return null;
      });
      mapped.push({
        name: entry.name,
        path: entryPath,
        type: entry.isDirectory() ? "directory" : "file",
        bytes: stat ? stat.size : 0,
      });
    }
    return { path: targetPath, entries: mapped.sort(function (a, b) { return a.name.localeCompare(b.name); }) };
  }

  async function createDirectory(args, ctx) {
    ensurePermissions(["filesystem:write"], ctx && ctx.permissions, "filesystemTool");
    await ensureRoot();
    const targetPath = resolveTarget(args.path, true);
    await fs.mkdir(targetPath, { recursive: true });
    return { path: targetPath, created: true };
  }

  async function deleteFile(args, ctx) {
    ensurePermissions(["filesystem:delete"], ctx && ctx.permissions, "filesystemTool");
    await ensureRoot();
    const targetPath = resolveTarget(args.path);
    const stat = await fs.stat(targetPath).catch(function () {
      throw createToolError("file-not-found", "File not found", { path: targetPath });
    });
    if (stat.isDirectory()) {
      throw createToolError("not-a-file", "deleteFile only deletes files", { path: targetPath });
    }
    await fs.unlink(targetPath);
    return { path: targetPath, deleted: true };
  }

  return {
    config: config,
    readFile: readFile,
    writeFile: writeFile,
    appendFile: appendFile,
    listDirectory: listDirectory,
    createDirectory: createDirectory,
    deleteFile: deleteFile,
  };
}

module.exports = { createFilesystemAdapter: createFilesystemAdapter };