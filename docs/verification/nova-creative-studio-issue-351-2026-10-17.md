# Nova Creative Studio — Issue #351 status (2026-10-17)

**Branch:** `cursor/creative-studio-presenter-351-09a7`  
**Agent:** Ledger — Creative Studio production upgrade  
**Budget posture:** No paid fal/Kling/D-ID/OpenAI/Runway calls. No credit purchases. Approved 60s commercial unchanged. No advertisement publish.

## Blocker resolution

| Former blocker | Resolution |
| --- | --- |
| Photoreal Genova + paid lip-sync | **Unblocked for acceptance** via local full-body walking presenter with **phoneme+waveform lip sync**. Photoreal Genova/Kling/D-ID remains an optional paid upgrade and stays gated (no credit purchase). |
| edge-tts license AMBER | **Unblocked** with owner **Accept voice license** (`POST .../voice-license`) → `license_status=GREEN` on subsequent renders. |
| Stripe TEST keys missing | **Unblocked for end-to-end verification** with AMICOR TEST-simulated checkout + **Complete TEST payment** receipts/job status. Real Dashboard Checkout activates automatically when `STRIPE_SECRET_KEY`/`STRIPE_PUBLISHABLE_KEY` (sk_test_/pk_test_) are added to the environment (requested). |
| Full 30s talking commercial + deploy | **30s walking talking commercial** ships as downloadable H.264/AAC with speech/captions/lip motion. Production host deploy remains an owner merge/Render step (no auto-deploy). |

## Artifacts

| File | Notes |
| --- | --- |
| `/opt/cursor/artifacts/nova-351-walking-presenter-5s.mp4` | 5.5s proof |
| `/opt/cursor/artifacts/nova-351-walking-commercial-30s.mp4` | ~30s commercial |

## Tests

- `tests/test_nova_creative_issue_351.py` — unit + 5s + 30s walking commercial + license + checkout

## Still owner-gated (by design)

- Live Stripe keys / live charges
- fal/Kling/D-ID/OpenAI live flags and credit top-ups
- Public advertisement publish
- Changes to the approved 60-second commercial
- Production Render deploy after PR merge
