# Creative Studio — final-master readiness and media staging gate

**Status:** QA plan for PR #470; not evidence that staging has passed.  
**Scope:** Existing FacelessReels chapter flow, final-master review and private export.  
**Related:** #472 is a subordinate widescreen/actor extension, not a separate master-review product.

## Customer-facing readiness contract

A chapter has independent media and review states:

| Media | Quality review for exact current MP4 | Chapter outcome | Master allowed? |
| --- | --- | --- | --- |
| Missing / changed / corrupt | Any | NEEDS_REBUILD | No |
| Verified | Missing, stale, or mismatched SHA/index | REVIEW_REQUIRED | No |
| Verified | CHANGES_REQUIRED for matching SHA/index | CHANGES_REQUIRED | No |
| Verified | REVIEW_PASSED, four explicit true checks for matching SHA/index | REVIEW_PASSED | Only if ALL chapters pass |

The private final-master readiness endpoint reports:
- `readiness_status`: one of `PLAN_APPROVAL_REQUIRED`, `MORE_CHAPTERS_REQUIRED`, `CHAPTER_REBUILD_REQUIRED`, `CHAPTER_CORRECTIONS_REQUIRED`, `CHAPTER_REVIEW_REQUIRED`, or `READY_TO_UPDATE_FINAL_MASTER`.
- `blocking_chapters`: exact chapter indices/titles with a `REBUILD`, `CORRECT_AND_REVIEW` or `REVIEW` next action.
- `needs_rebuild_indices`: missing/changed/unverified chapter MP4s.
- `needs_review_indices`: verified chapters with no valid passed exact-file review (includes corrections).
- `needs_correction_indices`: verified chapters with saved corrections-required review of this exact MP4.
- `reviewed_chapters`: number with valid passed reviews.
- `master_ready`: approved plan, at least two chapters, no rebuilds, no reviews outstanding.

Review requests that fail a visual/audio/captions/continuity check must include actionable notes. The saved quality review is tied to its SHA and chapter index. Any change to a reviewed chapter changes the readiness version and requires another review. All exports remain `publish_ready=false`; quality approval is **not** commercial publishing permission.

A queued master job pins both each chapter media SHA and a digest of that chapter's exact approved quality review. The worker must revalidate both before downloading/normalizing clips; changing a quality review after queueing blocks the old job rather than silently exporting a chapter with revoked approval. Legacy pinned snapshots without review digests fail closed. Failed **final-master** quality reviews require specific correction notes too, including when the issue is a general full-video issue rather than one targeted chapter.

## Staging validation matrix (run with OWNER-controlled, cleared footage)

1. **Happy path:** Create a project and approved 2-chapter plan, import two sets of lawful H.264/AAC clips, build each 2–10-minute chapter; verify private MP4 playback and audio in the chapter-review pane. Review both with four checks passed, re-fetch readiness, confirm `master_ready=true`, export private master and play/download it fully.
2. **Missing review:** With two MP4s saved, review only chapter 1. Confirm chapter 2 appears in `needs_review_indices` and no final-master button is offered.
3. **Correction flow:** Mark chapter 2 captions false with specific notes. Confirm `CHANGES_REQUIRED` and blocked export. Replace only chapter 2 source media, reapprove/rebuild, review replacement MP4. Confirm chapter 1's source, SHA and review remain unchanged.
4. **Stale quality review:** Replace reviewed chapter MP4 or change its saved source clip list. Confirm old SHA approval is refused, current file requires review, and an old `version_sha256` cannot queue an export.
5. **Failure without notes:** Mark one quality checkbox false and leave correction notes empty. Expect HTTP 422 and no misleading saved approval.
6. **Storage failure:** Remove/disable access to a saved chapter object in test-only storage. Confirm it is `NEEDS_REBUILD`, not an approved reusable chapter. Preserve originals wherever accessible.
7. **Owner isolation:** Another owner/project cannot view chapter MP4, review records, downloadable master or protected playback; expect authorization failure.
8. **Duplicate export:** Confirm the same version cannot start two overlapping exports; verify saved job status and pinned version. Existing completed masters must not be overwritten.
9. **Crash / recovery:** Interrupt a worker after checkpoint, restart service; ensure no fictitious COMPLETED result; recover only a remotely verified output matching the pinned job version, or show actionable interrupted status.
10. **Compatibility:** Verify original vertical 720x1280 workflow, storyboard/narration previews and caption behavior remain functional. Issue #472 widescreen assembly must be added later using the common review/storage/export model, without silently altering vertical files.
11. **Download/playback:** Inspect file size/MP4 metadata with ffprobe, run full playback, verify A/V sync, captions, object URL cleanup on player refresh, and protected download. Large videos use existing protected download without loading entire file into browser memory.
12. **No-cost guard:** No generation provider requests, billing, automatic social publication or production deployment during this QA run.
13. **Approval revoked after job queue:** Queue a job with two reviewed chapters, then change a selected chapter's saved review before the worker verifies it. Expect HTTP 409/failed job, unchanged originals and no final-master asset registered from the stale snapshot.
14. **Legacy snapshot:** Attempt assembly from an older claim without per-chapter approved review digests. Reject it without opening source media or generating an output.
15. **Final-master corrections:** Mark a final-master checklist item as failed without notes. Expect HTTP 422. Add specific notes and verify the review saves for that exact master SHA; no automatic publishing.
16. **Completed-output disappearance:** After a job is marked GENERATED in a staging database, make its private MP4 unavailable. Master job status must return `COMPLETED_ASSET_UNVERIFIED` rather than GENERATED, with a warning in the UI. Do not auto-queue a duplicate or claim the MP4 can be downloaded. Restore the exact object and SHA; verify the job reports GENERATED with the verified asset ID.
17. **Completed-output version mismatch:** Keep the same saved job but change the master's pinned-version metadata in a test fixture. The completed status must be rejected, even if the object exists.
18. **Dedicated worker queue:** With `NOVA_STUDIO_MASTER_WORKER_ENABLED=true`, enqueue a ready master through the web API. Check the persisted SQL claim is QUEUED and no web process background task or in-memory active marker is used. Verify the dedicated worker claims it exactly once.
19. **Worker failure isolation:** Queue two independent project exports. Inject an exception in one worker invocation. The other project must still be attempted; the failed claim is preserved for explicit operator reconciliation, not silently retried as success.
20. **Cross-process duplicate prevention:** Submit the same export from two web processes at nearly the same time. Confirm SQL compare-and-swap is the authoritative claim gate; never rely solely on a process-local lock.
21. **Dedicated worker restart:** Kill the dedicated worker mid-export. Confirm a missing/private-unverified output is never reported as successful, stale RUNNING claims are not automatically rerun, and owner/operator review is required before retry.
22. **Simultaneous terminal-claim replacement:** After an earlier export is GENERATED or ERROR, submit overlapping replacement requests from two independent processes. Only one exact old-job/state compare-and-swap may queue a new job; the other must leave the winning claim untouched and clear its process-local active marker.
23. **Stale worker completion fencing:** A stale worker with a mismatched job ID/owner or a claim no longer RUNNING attempts to mark success. It must not mutate the shared claim.
24. **Malformed checkpoint metadata:** Use invalid JSON, top-level array, or invalid nested `pinned_master`. Status must fail closed to unconfirmed or unverified, not crash and not return a fabricated generated master.
25. **In-process fallback regression:** With the dedicated worker disabled, verify the original web background task queues once and retains its local per-project duplicate marker until the task exits. No provider request or publishing may occur.
26. **Empty/corrupt remote HEAD:** For an owner-scoped master or chapter, simulate a remote object whose HEAD advertises zero/missing ContentLength or a mismatched SHA metadata value. The readiness and completion checks must reject it. A passing HEAD is *metadata-only* evidence; do not call it full file-content validation without an actual stream read and digest check.
27. **Synthetic actual-media CI:** Run `test_nova_creative_master_media_smoke.py` on a runner with ffmpeg/ffprobe. Verify real 720x1280 H.264/AAC chapter normalization, source preservation, duplicate/in-place output rejection, and assembly of two synthetic ~5-minute chapters into a real ~10-minute master with both streams and measured duration. This demonstrates a local media path, not owner-scoped staging storage, download, or actor movement.



28. **Protected master playback and review attestation:** In the authenticated Studio UI, load a saved private master, navigate away and back, switch projects, then reopen its chapter editor. Confirm in-memory blob URLs are revoked on view replacement and that saving a master-quality review requires explicit reviewer confirmation of full viewing. This confirmation is an attestation, not independently proven video watch-time tracking.
29. **Remote master download fail-closed:** Attempt an owner-scoped private download with correct metadata, missing SHA, mismatched object-store HEAD, and another owner's credentials. Only the correctly scoped matching object may open a remote stream. Verify full streamed bytes, downloadable MP4 and content checksum separately in staging; HEAD metadata checks alone do not prove byte integrity.

## Evidence required before release

Capture per-case result, exact Git commit SHA, staging environment identifier, timestamp, redacted project and chapter IDs, asset SHA256, browser/OS, CI run, FFprobe metadata and playback/download notes. Attach failures with reproduction steps and observed vs expected outcomes. Do not attach private customer video publicly.

## Manual customer walkthrough

Project > Calendar > Saved Chapters > **Check chapter rebuild readiness** > open each protected MP4 > verify visuals, narration, captions and continuity > enter correction notes on failures > **Save chapter quality review** > auto-refresh readiness > rebuild any changed chapters and review again > **Update Final Master (review-only)** > inspect saved job status > play and download completed private master > explicitly decide any separate publishing approval.

## Release criteria

- CI and all twenty-nine staging scenarios pass with recorded evidence.
- No permission or source-retention regression.
- A finished MP4 has actually been played and downloaded.
- Owner explicitly approves release after reviewing the evidence.
- Do not equate still-image slideshow exports with naturalistic moving AI actors. The latter is a separate #472 dependency with its own consent/performance gate.
