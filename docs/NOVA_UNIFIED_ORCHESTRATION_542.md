# Unified Nova Orchestration — architecture discovery and first integration contract

**Issue:** #542  
**Status:** Design-only, isolated review branch. Not merged, tested or deployed.  
**Owner controls:** No live outreach, paid providers, migrations, real lead imports, external communications or changes to protected production Core V1.

## Findings verified from repository source
1. `backend/app/core/nova/actions.py` already implements `ExecutionOrchestrator`: stage/propose action, scoped correlation, approval lifecycle, simulation, execution diagnostics and timelines. Reuse rather than invent a competing Nova Brain.
2. `backend/app/core/nova/action_models.py` already defines `NovaAction`, `ProposedAction`, approval requests, execution status and tenant scope. Its `ActionType` enum is operations-centric, so multi-agent routing requires an explicitly versioned adapter or separately reviewed extension.
3. `backend/app/core/nova/execution_intelligence.py` exposes pending approvals, failures and rollback snapshot diagnostics. Existing fallbacks to empty results must not be interpreted as evidence of success or zero live customer jobs.
4. `backend/app/core/nova/workspace/router.py` provides the existing authenticated Workspace API and organization resolution via `NovaCoreService.resolve_organization_scope`. Do not bypass tenant or owner-role checks.
5. `backend/static/orchestrator.js` is a browser chat/message/stream orchestrator. Agent routing is documented as **future work**, not an operational multi-agent dispatcher.
6. `docs/AMICOR_NOVA_CORE_V1_PRODUCTION_FREEZE.md` specifies one Mrs. Nova Brain with linked product surfaces, **not merged databases**. Any extension must respect V1 freeze and Health/Delivery/Freight isolation.
7. Existing unmerged candidates: Growth #490; Workspace owner status #517 (owner-role guard unresolved); first-customer campaign #519; Operations Work & Revenue #477; Creative Studio #515. Do not treat these as deployed or combine by blind merging.

## Proposed v0.1 cross-agent event envelope (design; NOT a live API)

```json
{
  "schema_version": "nova.agent-event.v0.1",
  "event_id": "unique-immutable-event-id",
  "correlation_id": "stable-org-scoped-customer-journey-id",
  "organization_id": "authorized-tenant-id",
  "source_agent": "creative_studio | growth | work_revenue | operations | hr",
  "target_agent": "growth | work_revenue | operations | hr | owner",
  "event_type": "asset_ready | lead_consented | lead_qualified | opportunity_review | task_approved | task_completed | human_assignment_needed | failed",
  "subject_reference": {"kind": "opaque-id-kind", "id": "opaque-owned-record-id"},
  "synthetic": true,
  "consent_reference": null,
  "approval_reference": null,
  "occurred_at": "RFC3339-UTC",
  "idempotency_key": "tenant-specific-unique-key",
  "payload_reference": "authorized-private-record-reference",
  "status": "proposed"
}
```

**No personal data, bank details, customer messages, access tokens or video bytes in event payloads.** Store only references; individual agents keep domain records in their own storage.

## Required contracts and gates
- **Creative Studio -> Growth:** Only an owner-approved campaign asset reference and attributed landing-page campaign code. Original five-second render not yet accepted; existing video playback cannot be represented as original generation.
- **Website -> Growth:** Reconcile legacy and future AMQ Cloudflare KV lead keys from #520; do not read `dedupe:` indexes as customer leads. Consent and AI disclosure mandatory before further contact.
- **Growth -> Work & Revenue:** Owner-visible qualified opportunity proposal; source provenance, permission scope and idempotency key. No automated offer or contract promise.
- **Work & Revenue -> Operations:** Only an authorized saved task approved by owner; retry-safe linking, no duplicate job, no live file handling before verification.
- **Operations -> HR:** Human-assignment request only when needed, never an unapproved employee action.
- **All agents -> Workspace/Brain:** Progress, outcome evidence, errors and next owner approval action with explicit synthetic/live labels.

## First acceptance slice
1. Synthetic Studio campaign asset reference gets a tracked source code (no publishing).
2. Synthetic website inquiry is ingested once, preserving consent and tenant scope; replay produces no duplicate.
3. Growth qualification proposes a reviewable Work & Revenue opportunity.
4. Owner approves the synthetic handoff, and Operations creates or reuses one matching saved task.
5. Workspace shows each status and next approval; failed handoff exposes retries and does not imply successful completion.
6. Negative tests: unauthorized user, wrong tenant, absent consent, replayed event, stale approval, restart, and disabled provider.
7. Original five-second Studio moving-video generation/play/download acceptance remains separately required by #499.

## Design decisions requiring code review
- Decide whether to extend existing `NovaAction` with agent routing fields or wrap it in a versioned immutable event model, avoiding Core V1 schema mutation.
- Decide durable outbox/inbox persistence per tenant, transaction boundary and recovery policy; existing in-memory dedupe alone is not sufficient proof of restart safety.
- Resolve the explicit owner-role guard blocker noted in PR #517 before any Workspace owner integration.
- Map HR interfaces from real code before creating assignment actions. No HR API verified in this audit.
- Check branch compatibility and CI for #490/#517/#519/#477/#515 before selecting implementation base.

## Proposed next engineering PR
A new isolated draft PR should implement **only** a pure event-schema and routing validation layer with tests (no endpoints, DB migration or live connections), reusing the existing auth/approval model after compatibility review. Then implement a synthetic read-only Workspace journey and controlled handoff in a later PR.
