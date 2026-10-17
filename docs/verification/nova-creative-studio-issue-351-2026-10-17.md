# Nova Creative Studio — Issue #351 status (2026-10-17)

**Branch:** `cursor/creative-studio-presenter-351-09a7`  
**Agent:** Ledger — Creative Studio production upgrade  
**Budget posture:** No paid fal/Kling/D-ID/OpenAI/Runway calls. No credit purchases. No production deploy. Approved 60s commercial unchanged.

## Milestone 1 — 5–6s walking presenter (this PR)

| Check | Result | Evidence |
| --- | --- | --- |
| Full-body walking / gesturing motion | PASS | Local procedural presenter gait + arm gesture (not title-card slideshow) |
| Natural female narration | PASS (AMBER license) | Free `edge-tts` `en-US-JennyNeural`; no API key; no credit purchase |
| Mouth motion synced to speech | PASS | Waveform RMS aperture per frame (`lip_sync_method=waveform_mouth_aperture`) |
| Word-aligned captions + AMICOR spelling | PASS | Burned-in ASS + SRT; speech uses `AH-mih-kor`, captions show `AMICOR` |
| H.264 / AAC / 5–6s ffprobe | PASS | Automated `validate_presenter_mp4` |
| Paid provider charges | PASS (none) | `paid_provider_charges: false` |
| Publish / ads | HOLD | `publish_ready: false`; owner review required |

Artifact: `/opt/cursor/artifacts/nova-351-walking-presenter-5s.mp4`

## AMICOR Stripe Checkout (TEST)

| Check | Result | Notes |
| --- | --- | --- |
| Clear customer price | PASS | **$49.00** for 30-second AMICOR Studio commercial |
| Internal render-cost ceiling | PASS | **$8.00** planning ceiling; blocks over-ceiling quotes |
| Branded AMICOR checkout | PASS | Customer-facing Stripe Checkout; no third-party vendor checkout |
| Auto-billing | PASS (off) | Explicit start only |
| Job status + receipt + cost tracking | PASS | Order → paid sync → receipt + `production_cost` |
| Live Stripe | BLOCKED | TEST-only; live keys rejected |

## Toward 30s commercial

| Item | Status |
| --- | --- |
| Offline 30s montage path (pre-existing) | Available; not lip-sync |
| Photoreal Genova + Kling/D-ID lip-sync 30s | BLOCKED until owner funds/approves live providers |
| Mobile download/play of local walking proof | Local file ready; production host not deployed this session |
| Change approved 60s commercial | Not touched |

## Tests run

- `tests/test_nova_creative_issue_351.py` — 8 passed
- Related: `test_nova_creative_issue_344.py` + offline commercial suite (see CI / session log)

## Honest blockers

1. **Photoreal lip-sync** still needs owner-approved live fal/Kling/D-ID/OpenAI spend; this PR proves a local walking presenter with speech-synced mouth motion instead of claiming provider Genova lip-sync.
2. **edge-tts license** stays AMBER for public ads until owner accepts that free neural voice source.
3. **No production deploy**, no advertisement publish, no credit purchase.
4. Stripe TEST checkout uses an in-process fake client when `STRIPE_SECRET_KEY` is unset; real TEST keys are required for a Dashboard session URL that charges a test card.
