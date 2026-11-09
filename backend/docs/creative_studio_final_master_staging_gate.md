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
- `needs_rebuild_indices`: missing/changed/unverified chapter MP4s.
- `needs_review_indices`: verified chapters with no valid passed exact-file review (includes corrections).
- `needs_correction_indices`: verified chapters with saved corrections-required review of this exact MP4.
- `reviewed_chapters`: number with valid passed reviews.
- `master_ready`: approved plan, at least two chapters, no rebuilds, no reviews outstanding.

Review requests that fail a visual/audio/captions/continuity check must include actionable notes. The saved quality review is tied to its SHA and chapter index. Any change to a reviewed chapter changes the readiness version and requires another review. All exports remain `publish_ready=false`; quality approval is **not** commercial publishing permission.

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

## Evidence required before release

Capture per-case result, exact Git commit SHA, staging environment identifier, timestamp, redacted project and chapter IDs, asset SHA256, browser/OS, CI run, FFprobe metadata and playback/download notes. Attach failures with reproduction steps and observed vs expected outcomes. Do not attach private customer video publicly.

## Manual customer walkthrough

Project > Calendar > Saved Chapters > **Check chapter rebuild readiness** > open each protected MP4 > verify visuals, narration, captions and continuity > enter correction notes on failures > **Save chapter quality review** > auto-refresh readiness > rebuild any changed chapters and review again > **Update Final Master (review-only)** > inspect saved job status > play and download completed private master > explicitly decide any separate publishing approval.

## Release criteria

- CI and all twelve staging scenarios pass with recorded evidence.
- No permission or source-retention regression.
- A finished MP4 has actually been played and downloaded.
- Owner explicitly approves release after reviewing the evidence.
- Do not equate still-image slideshow exports with naturalistic moving AI actors. The latter is a separate #472 dependency with its own consent/performance gate.
