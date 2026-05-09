# AUTH_ARCHITECTURE.md — Amicore Authentication & User Platform Layer

## Overview

The authentication layer provides a complete, dependency-free user account system built on Node.js built-in modules only (`crypto`). All state is held in in-memory Maps designed to be drop-in replaceable with a real database adapter.

---

## Module Map

```
backend/static/auth/
├── authSchemas.js         — Shared enums, factory functions, validators
├── tokenService.js        — HMAC-SHA256 token issuance and verification
├── sessionManager.js      — Multi-device session lifecycle
├── authManager.js         — Core auth operations (signup/login/logout/refresh)
├── permissionManager.js   — Role-based access control (RBAC) + per-user grants
├── userSettings.js        — Per-user settings CRUD with validation
├── userProfileManager.js  — User profile (displayName, avatar, bio, timezone, locale)
├── workflowPersistence.js — Per-user workflow and conversation persistence
├── authMiddleware.js      — Request-level auth context / ownership enforcement
└── index.js               — Barrel export

frontend/src/auth/
├── LoginPage.jsx          — Login form view-model
├── SignupPage.jsx         — Signup form view-model
├── SessionProvider.jsx    — Frontend session context with pluggable storage
├── UserSettings.jsx       — Settings panel view-model
├── ProfilePanel.jsx       — Profile editor view-model
├── SessionRecovery.jsx    — Token refresh / session recovery flow
└── index.js               — Barrel export
```

---

## Authentication Flow

### Signup
```
Client → signup({ email, password, displayName? })
  → validate email format
  → validate password strength (≥8 chars)
  → check no duplicate email
  → generateSalt() → 32-byte random salt
  → hashPassword(password, salt) → PBKDF2-SHA512, 100k iterations, 64-byte key
  → createUser(…) → in-memory users Map
  → createSession({ userId }) → sessionManager
  → issueAccessToken + issueRefreshToken
  ← { ok, userId, accessToken, refreshToken, sessionId, user }
```

### Login
```
Client → login({ email, password, deviceLabel? })
  → look up user by email
  → even if not found: run a dummy hash to prevent timing-based user enumeration
  → timingSafeEqual(stored hash, computed hash)
  → if mismatch → AUTH_ERRORS.invalidCredentials
  → createSession({ userId, deviceLabel })
  → issueAccessToken + issueRefreshToken
  ← { ok, userId, accessToken, refreshToken, sessionId, user }
```

### Logout
```
Client → logout(sessionId)
  → sessionManager.revokeSession(sessionId)
  ← { ok }
```

### Token Refresh
```
Client → refreshSession(refreshToken)
  → tokenService.verifyRefreshToken(refreshToken)
  → validate session still valid
  → tokenService.issueAccessToken(userId, role, sessionId)
  ← { ok, accessToken, userId }
```

### Password Change
```
Client → changePassword({ userId, currentPassword, newPassword })
  → get user → timingSafeEqual(current)
  → validate newPassword strength
  → generateSalt() + hashPassword(newPassword)
  → update user record
  → revokeAllUserSessions (forces re-login everywhere)
  ← { ok }
```

---

## Token Design

Tokens are 3-part base64url strings: `header.payload.signature`

| Field       | Type   | Notes                                  |
|-------------|--------|----------------------------------------|
| `sub`       | string | userId                                 |
| `role`      | string | ROLES enum value                       |
| `sessionId` | string | links token to a live session          |
| `type`      | string | "access" / "refresh" / "reset"         |
| `iat`       | number | issued-at (ms timestamp)               |
| `exp`       | number | expiry (ms timestamp)                  |

Signature: `HMAC-SHA256(header + "." + payload, secret)` — base64url encoded.

**TTLs:**
- Access token: 1 hour
- Refresh token: 30 days
- Reset token: 15 minutes

Type checking is enforced — a refresh token cannot be used where an access token is expected.

---

## Session Lifecycle

```
createSession → status: active
    │
    ├─ touchSession()  → expiresAt extended (on each authenticated request)
    │
    ├─ revokeSession() → status: revoked  (logout)
    │
    └─ isSessionValid() check:
         expiry passed? → status: expired
         status != active? → invalid
```

### Multi-Device Cap
- Default maximum: 5 concurrent sessions per user.
- When the cap is exceeded: the oldest session (by `createdAt`) is evicted automatically.
- All sessions for a user can be revoked at once (`revokeAllUserSessions`) — used on password change.

---

## Security Model

| Concern                  | Implementation                                                  |
|--------------------------|-----------------------------------------------------------------|
| Password hashing         | `crypto.pbkdf2Sync` — SHA-512, 100 000 iterations, 64-byte key |
| Per-user salt            | `crypto.randomBytes(32)` — unique per signup                   |
| Timing-safe comparison   | `crypto.timingSafeEqual` — prevents timing-based enumeration   |
| Dummy hash on login miss | Always hash on login even for unknown emails                   |
| Token signing            | HMAC-SHA256 with server-side secret                            |
| Token type enforcement   | Type field checked in `verifyAccessToken`/`verifyRefreshToken` |
| Session binding          | Token's `sessionId` must match a live active session           |
| No external dependencies | Only Node.js built-in `crypto` module used                     |

---

## Role Hierarchy & RBAC

```
guest (0)  <  user (1)  <  admin (2)  <  owner (3)
```

Built-in permissions per role:

| Role  | Permissions                                              |
|-------|----------------------------------------------------------|
| guest | `read:public`                                            |
| user  | `read:own`, `write:own`, `read:public`                   |
| admin | `read:own`, `write:own`, `read:public`, `manage:users`, `read:any`, `write:any` |
| owner | `*` (wildcard — all permissions)                         |

Extra permissions can be granted or revoked per user via `permissionManager.grantPermission(userId, perm)`.

`assertPermission` / `assertRole` return `{ ok, error }` — safe for middleware chains without throwing.

---

## User Isolation

Every data store in the auth layer is keyed by `userId`:

- `sessionManager` — `userSessionIndex: Map<userId, Set<sessionId>>`
- `workflowPersistence` — `workflowsByUser: Map<userId, Map<workflowId, workflow>>`
- `workflowPersistence` — `conversationsByUser: Map<userId, Map<convId, conv>>`
- `userProfileManager` — `profiles: Map<userId, profile>`
- `userSettings` — `settingsStore: Map<userId, settings>`

`authMiddleware.requireOwnership(context, resourceOwnerId)` enforces that a user can only access their own resources. Admins and owners bypass this check.

---

## Persistence Model

All stores use in-memory JavaScript `Map` objects. The design is adapter-ready:

- Each store can be replaced by a class/object implementing the same `get/set/delete/list` interface backed by a database, Redis, or remote API.
- The `workflowPersistence` module already accepts a `storage` option hook for future backends.
- Frontend modules accept `settingsAdapter` / `profileAdapter` / `refreshAdapter` dependency injection for backend connectivity.

---

## Frontend Patterns

All frontend auth components are **view-model factories** (not React components). They use a **subscriber/notify pattern** compatible with any rendering layer:

```js
var page = createLoginPage({ onLogin: myHandler });
var unsub = page.subscribe(function(state) { render(state); });
page.setField("email", "user@example.com");
await page.submit();
unsub();
```

State is always returned as a shallow clone — no mutation of internal state from outside.

---

## Session Recovery Flow

```
App boot → SessionProvider.hydrate()
         → reads accessToken + refreshToken from storage
         → SessionRecovery.attemptRecovery()
              │
              ├─ accessToken valid + session active → proceed
              │
              └─ accessToken missing/expired
                   → call refreshAdapter(refreshToken)
                   → success → SessionProvider.setSession(newSession) → proceed
                   → failure → SessionProvider.clearSession() → redirect to login
```

---

## Test & Benchmark Coverage

```
npm run test:auth          → runAuthTests.js   (unit + integration tests)
npm run benchmark:auth     → runAuthBenchmarks.js (throughput batches)
```

Benchmark batches:
1. `signup-throughput` — 100 unique signups
2. `login-throughput` — 100 logins across 50 pre-seeded users
3. `token-issue-access` — 200 access token generations
4. `token-verify-access` — 200 access token verifications
5. `token-refresh` — 100 refresh operations
6. `session-create` — 200 session creations
7. `session-lookup` — 200 session list lookups
8. `session-touch` — 100 session touches
9. `permission-check-role` — 500 role hierarchy checks
10. `permission-check-specific` — 500 specific permission checks
11. `profile-read` / `profile-update` — 200/100 ops
12. `settings-get` / `settings-update` — 200/100 ops
13. `workflow-save` / `workflow-list` / `conversation-save` — 200/100/200 ops
