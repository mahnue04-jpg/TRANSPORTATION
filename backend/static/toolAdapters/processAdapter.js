"use strict";

const { spawn } = require("child_process");
const path = require("path");

const {
  validateCommand,
  validateProcessArgs,
  ensurePermissions,
  ensureWithinLimit,
  estimateSize,
} = require("../toolSecurity");

const { createToolError } = require("./baseAdapter");

function createProcessAdapter(options) {
  const config = Object.assign(
    {
      allowlist: ["node"],
      cwd: path.resolve(process.cwd(), "backend/static/.real-tool-sandbox"),
      timeoutMs: 5000,
      maxOutputBytes: 256 * 1024,
      env: {},
    },
    options || {}
  );

  async function spawnProcess(args, ctx) {
    ensurePermissions(["process:spawn"], ctx && ctx.permissions, "processTool");
    const command = validateCommand(args.command, config.allowlist);
    const commandArgs = validateProcessArgs(args.args || []);
    const cwd = args.cwd ? path.resolve(config.cwd, args.cwd) : config.cwd;
    const startTime = Date.now();

    await require("fs/promises").mkdir(cwd, { recursive: true });

    return new Promise(function (resolve, reject) {
      let stdout = "";
      let stderr = "";
      let finished = false;
      const child = spawn(command, commandArgs, {
        cwd: cwd,
        shell: false,
        windowsHide: true,
        env: Object.assign({}, process.env, config.env, args.env || {}),
      });

      const timeout = setTimeout(function () {
        child.kill();
        reject(createToolError("process-timeout", "Process exceeded timeout", { timeoutMs: args.timeoutMs || config.timeoutMs }));
      }, args.timeoutMs || config.timeoutMs);

      function done(error, result) {
        if (finished) {
          return;
        }
        finished = true;
        clearTimeout(timeout);
        if (error) {
          reject(error);
        } else {
          resolve(result);
        }
      }

      child.stdout.on("data", function (chunk) {
        stdout += chunk.toString("utf8");
        ensureWithinLimit(estimateSize(stdout), config.maxOutputBytes, "Process stdout");
        if (ctx && typeof ctx.emitChunk === "function" && args.streamStdout) {
          ctx.emitChunk(chunk.toString("utf8"));
        }
      });

      child.stderr.on("data", function (chunk) {
        stderr += chunk.toString("utf8");
        ensureWithinLimit(estimateSize(stderr), config.maxOutputBytes, "Process stderr");
      });

      child.on("error", function (error) {
        done(error);
      });

      child.on("close", function (code, signal) {
        const durationMs = Date.now() - startTime;
        if (code !== 0) {
          done(
            createToolError("process-exited-nonzero", "Process exited with a non-zero code", {
              code: code,
              signal: signal,
              stdout: stdout,
              stderr: stderr,
              durationMs: durationMs,
            })
          );
          return;
        }
        done(null, {
          command: command,
          args: commandArgs,
          code: code,
          signal: signal,
          stdout: stdout,
          stderr: stderr,
          durationMs: durationMs,
        });
      });

      if (ctx && ctx.signal && typeof ctx.signal.addEventListener === "function") {
        ctx.signal.addEventListener("abort", function () {
          child.kill();
          done(createToolError("process-cancelled", "Process was cancelled"));
        });
      }

      if (ctx && typeof ctx.isCancelled === "function") {
        const poll = setInterval(function () {
          if (ctx.isCancelled()) {
            clearInterval(poll);
            child.kill();
            done(createToolError("process-cancelled", "Process was cancelled"));
          }
        }, 50);
        child.once("close", function () {
          clearInterval(poll);
        });
      }

      if (args.input) {
        child.stdin.write(String(args.input));
      }
      child.stdin.end();
    });
  }

  return {
    config: config,
    spawnProcess: spawnProcess,
  };
}

module.exports = { createProcessAdapter: createProcessAdapter };