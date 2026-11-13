# AMICOR Nova Voice Engine — phase 0 feasibility

Status: research/prototype plan only. No cloud GPU allocation, model deployment, subscription, provider call, or production code activation.

## Objective
Investigate an AMICOR-operated text-to-speech service that can pronounce "AMICOR Nova" correctly, produce natural professional English female narration, and hand audio to the existing Creative Studio pipeline. The user-approved $2.04 Creative Studio quote is **not** authorization for any new Nova Voice infrastructure expense.

## First implementation choices
- Prefer an openly licensed speech model with a commercially compatible license; verify both model weights and voice/data dependencies before customer usage. Initial candidate: Kokoro.
- Begin with CPU or local evaluation only if enough capacity is already available. Do not provision paid GPU services automatically.
- Separate the inference adapter from the Studio HTTP routes. No provider flags changed in production.
- Avoid blindly replacing "AMICOR" in written captions. Pronunciation dictionary may map spoken text to "Ammy Core" for audio only while preserving branded captions.
- Record voice model name and version, runtime, job id, owner/project access control, and estimated resource time. Do not store credentials in source or logs.

## Acceptance tests for first usable prototype
1. Produce playable English narration as WAV or MP3 from the approved commercial script, without a paid outside speech API.
2. Human reviewer confirms "AMICOR Nova" pronunciation and voice quality.
3. Audio duration fits the 30-second production target after pauses and edits.
4. Script text and visible captions preserve "AMICOR Nova" branding.
5. Keep existing Creative Studio provider as a fallback; never silently charge it.
6. Fail clearly when no local model/runtime is available; don't substitute a text-only GENERATED asset for real audio.
7. The engine must not invoke paid providers or auto-download multi-gigabyte models during import or tests.

## Cost gates
Phase 0: $0 incremental cash authorization; research and code-only tests.
Phase 1: proposed maximum $100, **not authorized**; obtain explicit owner approval before new infrastructure/cloud usage.
Do not add recurring subscriptions.

## Milestones and stop/go
- Week 1: license, dependencies, hardware feasibility, first isolated adapter/tests.
- Weeks 2–4: real voice output and pronunciation QA, packaging and security review.
- Weeks 5+: Studio integration after verified audio and cost/reliability data.
- Stop if voice quality, license, or processing cost is not competitive with an external API.

## Relationship to existing work
PR #416 is the separate budget and presenter voice repair. It stays unchanged and should not be merged as a prerequisite to phase-0 feasibility.
