# Real Tool Architecture

## Adapter Model

The real tools are implemented as a thin registration layer on top of `AmiCorToolRuntime`.
Each tool module exposes a `create*Tool()` factory that returns a runtime-compatible tool definition with:

- `name`
- `description`
- `schema`
- `permissions`
- `execute(args, ctx)`
- `metadata.lifecycle`

The runtime stays unchanged. Tool execution is delegated to adapter modules under `backend/static/toolAdapters/`, while security checks live under `backend/static/toolSecurity/`.

## Security Boundaries

The adapters enforce explicit sandbox boundaries before any I/O occurs:

- Filesystem access is rooted to a sandbox directory and rejects path traversal.
- File extensions are allowlisted before reads or writes.
- HTTP requests are GET-only, domain allowlisted, and blocked from localhost or internal network targets.
- Process execution uses a strict command allowlist and does not enable shell execution.
- Size limits are enforced for file content, HTTP responses, and process output.

## Execution Flow

1. A tool is registered with `AmiCorToolRuntime`.
2. The runtime validates the tool schema and permissions.
3. The adapter receives `args` plus the isolated execution context.
4. Security helpers sanitize paths, validate domains, enforce size limits, or guard subprocesses.
5. Tool-specific lifecycle hooks run before and after execution.
6. Structured results or structured errors are returned to the runtime.

## Sandboxing

The current sandbox strategy is filesystem-root based:

- Each test or benchmark run creates an isolated root directory.
- Tool adapters resolve all file and document paths relative to that root.
- Process execution uses the sandbox root as the working directory.
- HTTP tools never reach internal or localhost addresses and can be tested with injected transports.

This gives deterministic behavior in tests without changing the runtime architecture.

## Future Extensibility

The adapter layer is intentionally narrow so future real tools can reuse the same scaffolding:

- Add new adapters under `backend/static/toolAdapters/`.
- Add new security helpers under `backend/static/toolSecurity/`.
- Register new tool definitions from `backend/static/tools/`.
- Expand benchmark scenarios in `backend/static/toolBenchmarks/`.

This structure keeps the runtime stable while allowing tool capabilities to grow independently.