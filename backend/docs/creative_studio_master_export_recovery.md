# Nova Creative Studio — Private master export recovery playbook

**Scope:** Draft PR #470, existing single Creative Studio. This document is a staged operator playbook, **not** evidence of a successful media export or authorization to modify production data.

## Safety rules

- Do not auto-retry an uncertain RUNNING job, automatically overwrite a master, or publish after recovery.
- Do not change review approvals to bypass export; pinned quality reviews must match exact MP4 SHA/index.
- Never disable tenant authorization, object-store checksum checks, billing gates, or original-media retention.
- Do not log customer clips, signed object URLs, storage credentials, unredacted customer metadata, or private scripts.
- Keep original chapter MP4s and prior master versions intact. Any replacement master is a new private review-only version.

## State guide

| API state | Meaning | Owner/customer action | Operator action |
| --- | --- | --- | --- |
| NOT_STARTED | No job recorded | Review all chapters, then queue | None |
| QUEUED | SQL job waiting for worker | Check status, do not duplicate | Inspect dedicated-worker health |
| RUNNING | Claimed job within active lease | Check status | Inspect worker/heartbeat without triggering another job |
| ERROR | Explicit confirmed failure; may be resumable | Review error, confirm any retry | Verify source media and pinned plan first |
| INTERRUPTED_UNCONFIRMED | Worker cannot be confirmed active and no verified result | Do not retry automatically | Determine whether any external worker still owns the claim |
| COMPLETED_ASSET_UNVERIFIED | Job record says GENERATED but exact private master is missing, unreadable, or version mismatched | Do not publish or trust download | Verify object-store accessibility, recorded SHA and pinned version |
| GENERATED | Exact result MP4 passes current storage/version validation | Review playback/download | Record verification evidence and customer review status |

A saved review of the master is distinct from **commercial clearance** and any public release decision.

## Investigation procedure

1. Record environment (staging/production), exact Git SHA, project and job IDs **redacted for shared logs**, job state and claim state. Identify whether `NOVA_STUDIO_MASTER_WORKER_ENABLED` is enabled. Do not print credentials.
2. Use the protected `master-status` route for the scoped owner and project. Inspect `checkpoint.stage` and the version pinned in the associated claim; never substitute a different completed master's version.
3. Confirm the claim's `owner_id`, `project_id`, `entry_id`, `job_id`, `state`, and `updated_at` against the selected job. If a different claim replaced it, stop and reconcile the newer job; do **not** update stale claims.
4. If recently QUEUED or RUNNING, first verify whether an external dedicated worker remains active. A web-process local marker cannot prove another process is dead.
5. If job is GENERATED, verify its exact `result_asset_ids` correspond to a private `calendar_chapter_master` asset, current job's `pinned_version_sha256`, and the recorded SHA. Check authorized object storage and play/download only through protected owner-scoped access.
6. If job reports `COMPLETED_ASSET_UNVERIFIED`, do not claim success or overwrite old masters. Investigate object-store availability and metadata integrity first.
7. If job reports `INTERRUPTED_UNCONFIRMED`, look for an already saved MP4 *for that job's pinned version* that was created after the job; the standard read-only status path may recover it if a remote SHA check passes. Otherwise escalate for operator review. An uncertain worker must not be silently replayed.
8. If job reports confirmed `ERROR` with `resumable=true`, recheck the current chapter plan, storage, exact-file quality reviews, version token, and remaining checkpoints before a customer-initiated retry.
9. For a permitted explicit retry, queue a **new private** job with an atomically fenced SQL claim. Check whether another caller won the claim; never force a state transition over QUEUED/RUNNING from a different job.
10. After export, verify complete playback, audible narration, captions, duration, no missing chapters, protected download, source retention, and that no paid provider or social-publishing job fired.
11. Record outcome and any relevant screenshot/FFprobe metadata without uploading private customer content into a public GitHub issue.

## Concurrency and corruption checks

- Claim replacement must match the **old job ID, terminal state, tenant, project and entry**. Failed compare-and-swap is *not* permission to retry blindly.
- Terminal worker state changes must match the exact RUNNING job/tenant/project/entry. An old worker cannot finish a replacement job.
- Corrupt JSON, missing `pinned_master`, or invalid nested checkpoint shape means **unconfirmed**, not successfully completed.
- If every dedicated worker candidate fails unexpectedly, use the normal poll backoff; never hot-loop SQL.
- If one job unexpectedly raises, other independent projects should still be attempted; do not automatically requeue the failed job.

## Release gate and escalation

Before production rollout, attach actual CI results; test dedicated and in-process modes, simultaneous web requests, worker restart, missing completed object, owner isolation, and chapter-review revocation after queue. The staging checklist at `creative_studio_final_master_staging_gate.md` is the companion test matrix.

**Current status at authoring:** This is a development runbook. Staging export and restart recovery are not certified, and PR #470 remains draft. No deployment or paid model generation is authorized by this document.
