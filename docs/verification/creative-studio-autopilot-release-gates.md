# Creative Studio — owner-controlled release gates

Status: **NOT RELEASE-APPROVED**. Related: #454 (MP4 import/protection), #406 (provider cost reporting), #465 (autopilot), #466 (quality gate).

This document is a reproducible *acceptance protocol*, not a claim that staging or production tests have happened. Never enable paid generation, connect owner social accounts, or deploy production based on this document alone.

## Required evidence for each test
Record date/time + time zone, staging commit SHA, environment/service name, build/run ID, test operator, synthetic test-account ID (never secrets), project ID, test media SHA-256, expected outcome, actual outcome, screenshot/video reference where applicable, and pass/fail. Store evidence privately; **never publish tokens, passwords, customer files, or signed media URLs**.

## Gate A — foundational storage, browser, and authentication
1. Use isolated staging and a disposable owner account with authorized sample media; verify logout/login and that signed-in UI never advertises both sign-in and sign-out.
2. Upload a known-good H.264/AAC MP4 in a real desktop browser, then a real mobile browser. Record browser/device, media duration, codec and file hash. Confirm upload status comes from server success, not merely a button click.
3. Play the imported video in the browser, seek across the timeline, hear audio, and confirm expected captions. Verify actual content (not just HTTP 200).
4. Download original; independently calculate SHA-256 and compare byte-for-byte with original fixture.
5. Run every supported cleanup and project reset path. Verify only disposable previews are deleted and original file remains playable/downloadable with unchanged hash.
6. Restart or replace staging service with the intended persistent disk configuration; repeat playback, download, and checksum comparison.
7. Attempt cross-project and cross-account read/download; must receive authorization rejection without leaking file data or private paths.
8. Attempt invalid MP4, truncated upload, oversized upload, interrupted transfer, repeated upload, expired login, and insufficient storage. Confirm actionable error, no false success, no orphaned media and safe recovery.
9. Preserve the real browser video, server logs (redacted), tested SHA and any defects. Any data loss, access failure, false success, or inability to recover is a **NO-GO**.

## Gate B — original video creation
1. Owner supplies topic, brand and style; Nova creates editable *original* draft script.
2. Owner reviews rights and consent for any images, voice or presenter; no unauthorized likeness, copied footage or unlicensed audio.
3. Render a 9:16 H.264/AAC MP4 with narration and legible captions using **free/offline or preapproved** resources.
4. Check file opens in common desktop/mobile players, exact duration, audio audibility, caption accuracy, timing and all scene transitions. Automatically flag missing or silent tracks.
5. Save project, reopen, edit, rerender, and download without losing earlier approved originals.
6. Report generation states accurately: queued, working, failed, ready-for-review. Never say 'published' or 'complete' for an empty shell.
7. Verify interruption/retry recovery and owner cost ceiling; no paid-provider POST unless separately authorized.

## Gate C — scheduling and platform integrations
1. Test with an owned, controlled test social account, authorized via official supported API and documented scopes. Check platform/account eligibility and app-review requirements first.
2. Default: owner approves individual videos. Optional autopilot mode requires explicit authorization of subjects, channels, cadence, budget, and expiry/review rules.
3. Verify scheduling across America/Chicago DST changes, platform rate limits, token expiry, revocation, cancellation and global pause.
4. Publish one authorized test video; independently verify the remote platform post exists and media quality is correct before marking 'published'.
5. Induce retry/timeout and prove idempotency prevents duplicate remote posts; preserve receipts and errors.
6. Disconnect the account and confirm no future post attempts; test that another tenant never sees its tokens or content.

## Gate D — pilot and launch
- Run an owner-observed desktop and mobile pilot with consenting testers.
- No unresolved P0/P1 defects involving data loss, security, incorrect-success status, duplicate publishing, provider spending, or inaccessible downloads.
- Record measured usability problems and fix before broad rollout. Never promise guaranteed views or income.
- Require rollback steps, alerting, cost audit logs, support escalation path and explicit owner sign-off for each production release.

## Reporting vocabulary
- **Not started**: no implementation or test evidence.
- **Implemented**: code exists, behavior not independently verified.
- **CI passed**: automated tests passed for the named commit.
- **Staging verified**: isolated staging browser + storage proof recorded against a commit.
- **Production verified**: owner-approved deployment followed by production smoke checks.
- **Blocked**: evidence or dependency missing; report exact blocker.

## Current snapshot (2026-11-08)
PR #454 remains draft and unmerged. Six pull-request CI workflow runs for commit `94510d729ab9b6a8d1537e5386568c30d346302b` reported success, but there is **no evidence in this document** of real staging browser playback, real persistent-disk restart survival or production verification. Paid generation and publishing remain outside this release authorization.
