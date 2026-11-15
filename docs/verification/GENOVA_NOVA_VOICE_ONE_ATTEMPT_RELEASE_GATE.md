# Genova Nova voice: one-attempt staging acceptance gate

Status: **NOT ACTIVATED / NO PROVIDER CALLS ALLOWED YET**.
Owner approval: one **voice-only** sample of the ABC book script, **maximum $1 total**, **no automatic retries**. This does **not** authorize a deployment to production, a paid video render, a second attempt, or alteration of the protected staging workspace.

## Exact voice task
- Voice: `nova`; provider model: `gpt-4o-mini-tts` (review provider model support/retirement before use).
- Script (the exact bytes must be hashed on the executing host, after final approval):
```
A colorful ABC coloring adventure begins here!
Meet My First ABC Animal Coloring Adventure.
Explore letters, animals, and coloring together.
A creative activity for families to enjoy.
From AMICOR Kids Learning.
Find the paperback on Amazon today!
Book link in the description.
```
- Audio-only test: no presenter lip-sync, image rendering, transcription, external publishing, or paid captions.

## Mandatory stop/go checks before any deployment or generation
1. Verify latest exact PR head CI, including focused non-billable guard tests and broader backend diagnostic. PR must remain unmerged unless separately authorized.
2. Identify and verify an **isolated staging service** independent of `nova-studio-validation-350` and its existing SQLite/projects/media/backups. Do not deploy to the protected staging service by default. Confirm no live traffic and no automatic deploy.
3. Keep `NOVA_CREATIVE_VOICE_LIVE_ENABLED=false` by default. Any temporary enabling must be on the isolated service only after ALL checks below; turn it back off afterward.
4. Verify the authorized provider account/project, prepaid balance or **provider-enforced** spending controls before submitting even one request. A GitHub test, project quote, estimate or local marker **is not a guaranteed $1 monetary cap**. If available controls cannot guarantee staying within the owner's cap, **STOP** and request a separate decision—do not treat this note as spending authorization beyond $1.
5. Verify actual selected model and *current* input/output prices and whether generation (including retries or background completion after timeout) is billable. Never use an unspecified cost multiplier or estimate as a guaranteed invoice ceiling.
6. Configure an existing, backed-up persistent **isolated** directory for `NOVA_CREATIVE_VOICE_TEST_CLAIM_FILE` (no collision with older projects). Never delete or reset its marker after a timeout or uncertain billing outcome.
7. Set `NOVA_CREATIVE_VOICE_SCOPED_TEST=true` and `NOVA_CREATIVE_VOICE_TEST_SCRIPT_SHA256` to SHA256 of exact script text; confirm voice `nova`, model `gpt-4o-mini-tts`, `presenter=false`. This optional guard rejects script/voice mismatch and uses OpenAI SDK `max_retries=0`, but does not cap tokens or provider charges.
8. Verify actual owner authentication and a project that does not affect protected media. No production secrets are placed in logs, code or PR comments.

## Single attempt and aftercare
- Before submit, screenshot/record approval, provider-side spend protection, model and exact script hash, but do not include API keys.
- Submit **one** voice-only request. Never click twice, never retry a timeout, and do not delete the marker.
- If completed, download and validate audio length/format and listen for pronunciation, clarity, warmth and natural pace. Store audio privately for owner review. Do not label a sample as a finalized advertisement.
- Turn live flag OFF after the attempt. Check provider usage/billing and preserve a redacted record of actual charge.
- Do not replace existing Studio media or change the prior approved 60-second demo; the book ad remains in draft until the owner approves voice and verifies final cover/captions.

**Current blocker:** No verified provider-enforced <= $1 invoice cap, so generation is **NOT AUTHORIZED TO RUN** under these conditions yet. Voice remains OFF.
