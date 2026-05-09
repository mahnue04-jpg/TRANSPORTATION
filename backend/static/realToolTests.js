"use strict";

const fs = require("fs/promises");
const os = require("os");
const path = require("path");

async function makeSandboxRoot(prefix) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), prefix));
  return root;
}

async function removeSandboxRoot(root) {
  await fs.rm(root, { recursive: true, force: true }).catch(function () {});
}

async function createRuntimeWithTools(env, overrides) {
  const sandboxRoot = await makeSandboxRoot("amicore-realtools-");
  const defaults = {
    filesystem: { rootDir: sandboxRoot },
    document: { rootDir: sandboxRoot },
    search: { rootDir: sandboxRoot },
    process: { cwd: sandboxRoot, allowlist: ["node"] },
    http: {
      allowlist: ["example.com"],
      transport: async function (parsedUrl, requestOptions) {
        return {
          statusCode: 200,
          headers: { "content-type": "text/plain" },
          body: "mock-response:" + parsedUrl.hostname + parsedUrl.pathname,
        };
      },
    },
  };
  const overrideConfig = overrides || {};
  const config = {
    filesystem: Object.assign({}, defaults.filesystem, overrideConfig.filesystem || {}),
    document: Object.assign({}, defaults.document, overrideConfig.document || {}),
    search: Object.assign({}, defaults.search, overrideConfig.search || {}),
    process: Object.assign({}, defaults.process, overrideConfig.process || {}),
    http: Object.assign({}, defaults.http, overrideConfig.http || {}),
  };

  const runtime = env.createRuntime();
  env.registerRealTools(runtime, config);
  return { runtime: runtime, sandboxRoot: sandboxRoot, config: config };
}

function basePermissions(toolName, extraPermissions) {
  const map = {
    filesystemTool: ["filesystem:use"],
    documentTool: ["document:use"],
    httpTool: ["http:use"],
    searchTool: ["search:use"],
    processTool: ["process:use"],
  };
  const merged = (map[toolName] || []).concat(extraPermissions || []);
  return Array.from(new Set(merged));
}

async function runRealToolTests(env) {
  const tests = [];
  let passed = 0;
  let failed = 0;

  function test(name, fn) {
    tests.push({ name: name, fn: fn });
  }

  function ok(condition, message) {
    if (!condition) {
      failed += 1;
      console.error("  ✗ FAIL: " + message);
      return false;
    }
    passed += 1;
    console.log("  ✓ " + message);
    return true;
  }

  function expectErrorCode(result, expectedCode, label) {
    ok(result && result.status === "error", label + " returned error status");
    const actualCode = result && result.error && result.error.code;
    ok(actualCode === expectedCode, label + " error code = " + expectedCode + " (got " + actualCode + ")");
  }

  test("filesystem path traversal blocked", async function () {
    const ctx = await createRuntimeWithTools(env);
    try {
      const result = await ctx.runtime.execute(
        "filesystemTool",
        { operation: "readFile", path: "../escape.txt" },
        { permissions: basePermissions("filesystemTool", ["filesystem:read"]) }
      );
      expectErrorCode(result, "path-traversal", "filesystem traversal");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("filesystem oversized write blocked", async function () {
    const ctx = await createRuntimeWithTools(env, { filesystem: { maxFileSize: 16 } });
    try {
      const result = await ctx.runtime.execute(
        "filesystemTool",
        { operation: "writeFile", path: "note.txt", content: "abcdefghijklmnopqrstuvwxyz" },
        { permissions: basePermissions("filesystemTool", ["filesystem:write"]) }
      );
      expectErrorCode(result, "size-limit-exceeded", "oversized write");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("filesystem concurrent access works", async function () {
    const ctx = await createRuntimeWithTools(env);
    try {
      const writes = [];
      for (let index = 0; index < 12; index++) {
        writes.push(
          ctx.runtime.execute(
            "filesystemTool",
            { operation: "writeFile", path: "docs/file-" + index + ".txt", content: "file-" + index },
            { permissions: basePermissions("filesystemTool", ["filesystem:write"]) }
          )
        );
      }
      const writeResults = await Promise.all(writes);
      ok(writeResults.every(function (result) { return result.status === "completed"; }), "all concurrent writes completed");

      const reads = [];
      for (let index = 0; index < 12; index++) {
        reads.push(
          ctx.runtime.execute(
            "filesystemTool",
            { operation: "readFile", path: "docs/file-" + index + ".txt" },
            { permissions: basePermissions("filesystemTool", ["filesystem:read"]) }
          )
        );
      }
      const readResults = await Promise.all(reads);
      ok(readResults.every(function (result) { return result.status === "completed"; }), "all concurrent reads completed");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("document chunking emits chunks", async function () {
    const ctx = await createRuntimeWithTools(env);
    try {
      const content = Array.from({ length: 80 }, function (_, index) {
        return "Line " + index + " lorem ipsum dolor sit amet.";
      }).join("\n");
      await fs.mkdir(path.join(ctx.sandboxRoot, "docs"), { recursive: true });
      await fs.writeFile(path.join(ctx.sandboxRoot, "docs/large.md"), content, "utf8");

      const result = await ctx.runtime.execute(
        "documentTool",
        { operation: "chunkDocument", path: "docs/large.md", chunkSize: 128 },
        { permissions: basePermissions("documentTool", ["document:read"]) }
      );

      ok(result.status === "completed", "document chunking completed");
      ok(result.output.chunkCount > 0, "document produced chunks");
      ok(result.chunks.length > 0, "runtime captured emitted chunks");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("document metadata and summary work", async function () {
    const ctx = await createRuntimeWithTools(env);
    try {
      await fs.mkdir(path.join(ctx.sandboxRoot, "docs"), { recursive: true });
      await fs.writeFile(path.join(ctx.sandboxRoot, "docs/story.txt"), "Alpha beta gamma. Delta epsilon zeta. Eta theta iota.", "utf8");

      const summary = await ctx.runtime.execute(
        "documentTool",
        { operation: "summarizeText", path: "docs/story.txt", maxSentences: 2 },
        { permissions: basePermissions("documentTool", ["document:read"]) }
      );
      ok(summary.status === "completed", "summary completed");
      ok(summary.output.summary.length > 0, "summary contains text");

      const metadata = await ctx.runtime.execute(
        "documentTool",
        { operation: "extractMetadata", path: "docs/story.txt" },
        { permissions: basePermissions("documentTool", ["document:read"]) }
      );
      ok(metadata.status === "completed", "metadata completed");
      ok(metadata.output.words > 0, "metadata includes word count");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("http timeout is enforced", async function () {
    const ctx = await createRuntimeWithTools(env, {
      http: {
        allowlist: ["example.com"],
        timeoutMs: 50,
        retries: 0,
        transport: function () {
          return new Promise(function (resolve) {
            setTimeout(function () {
              resolve({ statusCode: 200, headers: {}, body: "slow" });
            }, 200);
          });
        },
      },
    });
    try {
      const result = await ctx.runtime.execute(
        "httpTool",
        { url: "https://example.com/slow", timeoutMs: 50, retries: 0 },
        { permissions: basePermissions("httpTool") }
      );
      expectErrorCode(result, "request-timeout", "HTTP timeout");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("http blocks localhost and internal targets", async function () {
    const ctx = await createRuntimeWithTools(env);
    try {
      const result = await ctx.runtime.execute(
        "httpTool",
        { url: "http://localhost/test" },
        { permissions: basePermissions("httpTool") }
      );
      expectErrorCode(result, "internal-host-blocked", "localhost request");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("http allowlisted mock transport succeeds", async function () {
    const ctx = await createRuntimeWithTools(env, {
      http: {
        allowlist: ["example.com"],
        transport: async function (parsedUrl) {
          return {
            statusCode: 200,
            headers: { "content-type": "text/plain" },
            body: "ok:" + parsedUrl.hostname,
          };
        },
      },
    });
    try {
      const result = await ctx.runtime.execute(
        "httpTool",
        { url: "https://example.com/health" },
        { permissions: basePermissions("httpTool") }
      );
      ok(result.status === "completed", "allowlisted HTTP call completed");
      ok(result.output.body.indexOf("ok:example.com") === 0, "allowlisted HTTP response returned");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("search returns paginated local results", async function () {
    const ctx = await createRuntimeWithTools(env);
    try {
      await fs.mkdir(path.join(ctx.sandboxRoot, "notes"), { recursive: true });
      await fs.writeFile(path.join(ctx.sandboxRoot, "notes/a.md"), "alpha beta gamma alpha", "utf8");
      await fs.writeFile(path.join(ctx.sandboxRoot, "notes/b.txt"), "beta alpha delta", "utf8");

      const result = await ctx.runtime.execute(
        "searchTool",
        { query: "alpha", page: 1, pageSize: 1 },
        { permissions: basePermissions("searchTool") }
      );

      ok(result.status === "completed", "search completed");
      ok(result.output.total >= 1, "search found at least one result");
      ok(result.output.items.length === 1, "search pagination applied");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("process allowlist rejects abuse attempts", async function () {
    const ctx = await createRuntimeWithTools(env);
    try {
      const result = await ctx.runtime.execute(
        "processTool",
        { command: "cmd", args: ["/c", "echo", "blocked"] },
        { permissions: basePermissions("processTool", ["process:spawn"]) }
      );
      ok(result.status === "error", "abusive process command returned error status");
      const message = result.error && result.error.message ? String(result.error.message) : "";
      ok(message.indexOf("allowlisted") !== -1 || message.indexOf("not allowed") !== -1, "abusive process command was blocked");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("process cancellation during execution is handled", async function () {
    const ctx = await createRuntimeWithTools(env, {
      process: { allowlist: ["node"] },
    });
    try {
      const execId = "process-cancel-" + Date.now();
      const promise = ctx.runtime.execute(
        "processTool",
        { command: "node", args: ["-e", "setTimeout(() => console.log('done'), 2000)"] },
        { permissions: basePermissions("processTool", ["process:spawn"]), execId: execId }
      );
      setTimeout(function () {
        ctx.runtime.cancel(execId);
      }, 50);
      const result = await promise;
      ok(result.status === "error" || result.status === "cancelled", "process result handled cancellation safely");
      const message = result.error && result.error.message ? String(result.error.message) : "";
      ok(!message || message.toLowerCase().indexOf("cancel") !== -1 || message.toLowerCase().indexOf("exit") !== -1, "process cancellation surfaced safely");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  test("permission denial is enforced", async function () {
    const ctx = await createRuntimeWithTools(env);
    try {
      const result = await ctx.runtime.execute("filesystemTool", { operation: "listDirectory", path: "." }, { permissions: [] });
      ok(result.status === "error", "permission denial returned error status");
      const message = result.error && result.error.message ? String(result.error.message) : "";
      ok(message.toLowerCase().indexOf("permission") !== -1, "permission denial surfaced through runtime");
    } finally {
      await removeSandboxRoot(ctx.sandboxRoot);
    }
  });

  for (const testCase of tests) {
    console.log("  ● " + testCase.name);
    try {
      await testCase.fn();
    } catch (error) {
      failed += 1;
      console.error("    ERROR: " + error.message);
    }
  }

  return {
    passed: passed,
    failed: failed,
    total: passed + failed,
  };
}

module.exports = { runRealToolTests: runRealToolTests };