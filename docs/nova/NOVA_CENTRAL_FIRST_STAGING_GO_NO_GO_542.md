# Nova Central — first isolated staging acceptance decision (owner gate)

**Status: NO-GO for deployment or provisioning. Planning document only.**

Reviewed draft #554 at `2ad6db1585c794972b18b4d0331e753aa31f0530`. The isolated CI run `44226548930` passed **104 tests / 11 warnings**. Backend diagnostic was still running when this document was drafted. No staging service or database has been provisioned.

## What exists, versus what does not

- Draft code: fail-closed, isolated readiness-only ASGI factory; auth uses only seven persisted account columns, owner/tenant restrictions, no live journeys, no agent dispatcher.
- Synthetic / disposable tests: config, auth, zero unauthorized writes for exercised requests, SQLite simulated restricted-reader denials, and pure PostgreSQL privilege-audit logic.
- Missing: a dedicated isolated Postgres instance, service, actual restricted role, owner-approved secrets/fixtures, validated backup/restore, actual Postgres GRANT denial tests, Render deployment acceptance, live multi-agent orchestration.
- Important: a successful unit suite is **not** permission to connect to production, shared databases, Studio SQLite/media or any existing Growth/Receptionist staging instance.

## Exact infrastructure proposal — not a creation instruction

| Resource | Proposed name | Requirements |
|---|---|---|
| Web service | `nova-central-validation-542` | New isolated service, auto-deploy OFF, exact approved SHA, minimum permissions, no workers or live providers |
| DB | `nova-central-542-dispos` | New **disposable**, isolated PostgreSQL resource with independent credentials and retention plan |
| Application DB role | `nova_central_542_reader` | Only approved DB, no privileged group membership, no schema/DB CREATE/TEMP, no unrelated table/function grants, seven-column SELECT on fictional `platform_users`, future journey SELECT only after separate approval |
| Migration/fixture identity | Separately named when approved | **Never** provided to web service, removed/revoked after fictional fixtures are installed |

These are suggested names, **not** existing resource IDs. Obtain the Render checkout tier, exact monthly price, region, expected storage/usage costs and backup/expiry behavior before asking for payment or resource creation.

## Go / no-go stages

### G0 — code and CI review (no spend)

- [x] Isolated focused tests passed: 104 at `2ad6db15` (synthetic/disposable).
- [ ] Review final full backend diagnostic **at the approved exact head**; any failed, stuck, or unrelated check must be documented separately, not assumed green.
- [ ] Review the complete stack #544–#554 and determine an approved merge strategy with exact heads and source dependencies. No automatic merge.
- [ ] Inspect ASGI import graph and any global connections/background tasks; reject shared startup or table/account seeding in the isolated process.
- [ ] Review the permission-audit catalog SQL against a disposable PostgreSQL instance for compatibility, PUBLIC/inherited/default grants, functions/procedures, schema and column-level SELECT. Pure tests cannot establish catalog compatibility.

### G1 — owner purchase/provision decision (requires explicit new approval)

- [ ] Provide proposed exact service and DB tiers/region, total recurring charge, any initial cost, retention/backup limits, restart behavior, and isolation from all other AMICOR resources.
- [ ] Obtain **explicit owner authorization** for specific **new** resources and price. No approval is implied by conversation requests to continue.
- [ ] Verify no sharing of `amicor-prod`, `nova-ga-490-dispos`, Receptionist DB, Studio disk/SQLite, secrets or common env group.
- [ ] Keep customer data, outbound transport, paid providers and live agents disabled.

### G2 — disposable database acceptance (requires provisioning and schema approvals)

- [ ] Apply only an explicitly approved schema and fictional fixture accounts using a temporary migration identity; back up before schema mutation and verify restore.
- [ ] Configure reader in PostgreSQL with only required seven-column identity SELECT and explicitly reviewed journey read SELECT (if enabled), no other table/column/function access.
- [ ] Execute *actual* denied SELECT on private column/unrelated table and denied INSERT/UPDATE/DELETE/CREATE/TEMP/role escalation with reader. Require SQL permission failures and captured redacted logs.
- [ ] Run catalog audit with exact approved reader URL, exact DB host and name, pinned source SHA and `NOVA_CENTRAL_PERMISSION_AUDIT_APPROVED=true` **only within an approved test window**.
- [ ] Record network restrictions, log redaction, retention, credential rotation/revocation and teardown.

### G3 — isolated service acceptance (separate deploy approval)

- [ ] Deploy exact reviewed commit to only the new staging service with both Central journey flags **false** at boot and auto-deploy OFF.
- [ ] Verify liveness, no unauthorized DB initialization/seed/worker execution, startup/shutdown logs, no outbound messages and no fees.
- [ ] With synthetic owner sessions, verify 401/403/404 as appropriate, tenant isolation and cache headers; a short-lived feature-preview window requires **another approval**.
- [ ] Validate recovery/rollback and disable any temporary previews. Confirm Studio, Growth, Receptionist and production systems remain unchanged.

### G4 — actual orchestration: separate future project

- [ ] Implement the real, consent-scoped agent dispatcher and durable, auditable cross-agent event storage; define work ownership, human approvals, idempotency, delivery failures and retention.
- [ ] Integrate Growth, Creative Studio, Operations, Work & Revenue, HR and Workspace one by one under explicit staging contracts.
- [ ] Require owner signoff before real-customer data access, paid providers, messages, production deployment or live revenue workflows.

## Release decision

**NO-GO** until G0 is complete and the owner approves G1 with exact resources and cost. Nothing here authorizes payment, merge, provisioning, migration, customer data access or production deployment. Do not mistake the public Cloudflare Pages preview for the isolated backend.
