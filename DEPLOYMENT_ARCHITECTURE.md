# Deployment Architecture

## Overview

Amicore's deployment and integration foundation is a set of pure-Node.js modules with no external dependencies. All modules use the CommonJS factory pattern (`createX(options)` → object with methods) and store state in closures. Every module is independently testable and composable.

---

## Module Map

```
backend/static/
├── integrations/
│   ├── integrationSchemas.js   — shared enums, uid(), factory functions
│   ├── integrationManager.js   — adapter registry + lifecycle
│   ├── apiConnector.js         — HTTP/HTTPS client (circuit breaker, retry)
│   ├── serviceAdapter.js       — base adapter wrapper (capability introspection)
│   ├── webhookSystem.js        — HMAC-signed delivery + retry
│   ├── emailProvider.js        — email abstraction (offline mock + plug-in)
│   ├── calendarProvider.js     — calendar CRUD (in-memory store)
│   ├── documentProvider.js     — file store with soft delete
│   ├── notificationProvider.js — per-user queues with priorities + eviction
│   └── index.js                — barrel export
│
├── deployment/
│   ├── deploymentSchemas.js    — shared enums, factory functions
│   ├── environmentConfig.js    — env-aware config manager
│   ├── secretsManager.js       — AES-256-GCM secrets store
│   ├── logger.js               — structured leveled logger + child contexts
│   ├── telemetry.js            — distributed tracing + metrics
│   ├── healthMonitor.js        — pluggable health checks + rollup
│   ├── rateLimiter.js          — sliding window + per-user quotas
│   ├── errorMonitor.js         — capture + fingerprint dedup + hooks
│   ├── deploymentValidator.js  — pre-deployment validation
│   └── index.js                — barrel export
│
└── deploymentBenchmarks/
    └── index.js                — benchmark runner + formatter

frontend/src/
└── integrations/
    ├── integrationClient.js    — view-model (connect/disconnect/list)
    ├── webhookClient.js        — view-model (register/unregister/list)
    ├── notificationClient.js   — view-model (load/markRead/poll)
    └── index.js                — barrel export
```

---

## Deployment Topology

### Environments

| Environment | `NODE_ENV` | Notes |
|-------------|-----------|-------|
| Development | `dev` / `development` | Verbose logging, debug spans |
| Staging | `staging` | Mirror of production with test credentials |
| Production | `production` | Secrets encrypted, all monitors active |

`createEnvironmentConfig` reads from an injected `env` map (defaults to `process.env`) and exposes `isDev()`, `isStaging()`, `isProduction()` helpers. Runtime overrides via `set(key, value)`.

### Secrets

`createSecretsManager` encrypts all secrets at rest with AES-256-GCM:
- IV: 12 random bytes (per secret)
- Auth tag: 16 bytes (integrity check)
- Master key: 32-byte Buffer, or string hashed via SHA-256, or randomly generated
- Stored as a single base64 blob: `base64(iv + tag + ciphertext)`
- Plaintext never appears in logs or the audit log

---

## Integration Architecture

```
integrationManager
     │
     ├── register(adapter)
     ├── connect(id)  →  adapter.connect(config)
     ├── disconnect(id) → adapter.disconnect()
     └── healthCheck(id) → adapter.healthCheck()
               │
         serviceAdapter
               │
         provider (email / calendar / document / notification / custom)
               │
         apiConnector (for remote providers)
```

- `integrationManager` maintains a registry keyed by integration ID
- `serviceAdapter` wraps any provider and normalises lifecycle + error handling
- `apiConnector` handles raw HTTP/HTTPS with circuit breaker and retry

### Circuit Breaker (apiConnector)

```
CLOSED → (N consecutive failures) → OPEN → (reset interval) → HALF-OPEN → (success) → CLOSED
                                                                          → (failure) → OPEN
```

Default thresholds: 5 failures to open; 30 s reset interval.

### Webhook Delivery

- Webhooks are registered per integration + event
- Dispatch fans out to all matching active webhooks
- Delivery is signed with HMAC-SHA256: `sha256=<hmac>` in the configurable header
- Retry: up to `maxRetries` (default 3) with exponential backoff capped at 10 s
- Delivery log per webhook (ring buffer, configurable size)

---

## Observability Model

### Logging (`logger`)

- Structured entries: `{ id, timestamp, level, message, context, data }`
- Levels: debug → info → warn → error → fatal (filtered by `setLevel`)
- Child loggers inherit + extend context (immutable merge)
- Transport array: any `fn(entry)` (console, file, remote)
- In-memory ring buffer: 1000 entries; filterable by level, time, context

### Tracing (`telemetry`)

- Span lifecycle: `startSpan(name, options)` → `endSpan(spanId, result)`
- `durationMs` computed on close; status `ok` or `error`
- Active spans in Map; completed in ring buffer (500 spans)
- Metric ring buffer: 1000 samples
- Pluggable flush: `telemetry.flush()` → calls injected `onFlush(spans, metrics)`

### Error Monitoring (`errorMonitor`)

- Capture any `Error` object
- Fingerprint = MD5(message + first stack frame), first 16 hex chars
- Deduplication: same fingerprint increments `count` + `lastSeenAt`
- Hooks: `addHook(fn)` called synchronously on every capture
- Ring buffer: 500 unique error records
- `getErrorRate(windowMs)` returns `{ count, ratePerSecond, windowMs }`

---

## Scaling Model

### Rate Limiting (`rateLimiter`)

- Algorithm: sliding window (timestamps per key, pruned on access)
- `consume(key, { maxRequests, windowMs })` — check + record
- `check(key, limits)` — read-only, does not consume
- Per-user quota types: `daily`, `hourly`, `perTool:<toolName>`, `concurrent`
- GC timer: every 5 min, prunes expired windows; timer is `.unref()`'d
- Call `destroy()` to clean up the GC timer

### Health Monitoring (`healthMonitor`)

- Register named checks: `registerCheck(name, async fn)`
- Each check has a per-instance timeout (default 5 s, via `Promise.race`)
- `runAll()` status rollup:
  - All pass → `healthy`
  - Some fail → `degraded`
  - All fail → `unhealthy`
- `getReport()` returns the last completed report

---

## Production Hardening Checklist

- [ ] Set `NODE_ENV=production` in environment
- [ ] Provide a 32-byte master key via a secret (not hardcoded)
- [ ] Load all required secrets via `secretsManager.setSecret()`
- [ ] Run `deploymentValidator.validateEnvironment()` at startup
- [ ] Run `deploymentValidator.validateSecrets()` with required key list
- [ ] Register health checks for all critical dependencies (DB, cache, external APIs)
- [ ] Wire `errorMonitor` hooks to alerting (PagerDuty, Slack, etc.)
- [ ] Set rate limiter quotas appropriate for your tier
- [ ] Set telemetry `onFlush` to emit to your APM backend
- [ ] Call `rateLimiter.destroy()` on graceful shutdown

---

## Test & Benchmark Commands

```bash
# Run full deployment + integration test suite
npm run test:deployment

# Run benchmarks (1000 iterations per batch)
npm run benchmark:deployment
```

Test pattern: custom `test(name, fn)` + `ok(condition, msg)` + `async run()` — no external dependencies.

Benchmark pattern: `createBenchmarkCollector` + `runBatch(label, count, executor)` + formatted report with avg, p50, p95, p99, ops/s.
