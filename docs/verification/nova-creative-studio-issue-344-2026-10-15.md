# Nova Creative Studio — Issue #344 status matrix (2026-10-15)

**Branch:** `cursor/nova-creative-studio-344-b2ae`  
**Paused:** Nova Snap #337 (no Snap work this session)  
**Budget posture:** No paid provider calls, no top-ups, no purchases. Owner-reported fal balance −$3.16.

## Live deployment smoke (unauthenticated)

| Check | Result | Evidence |
| --- | --- | --- |
| `GET /nova/creative` | PASS | HTTP 200 — Studio shell loads |
| `GET /static/nova-creative/creative.js` | PASS | HTTP 200 — matches repo hash at audit start |
| `GET /api/health` | PASS | HTTP 200 |
| `GET /api/nova/creative/guardrails` | PASS | HTTP 401 Authentication required (expected) |
| Authenticated mobile login loop | BLOCKED | No owner credentials in this agent session |
| Provider status after login | BLOCKED | Requires authenticated session |
| Paid Kling / D-ID / OpenAI render | BLOCKED | fal balance negative; live flags must stay gated; preflight blocks paid confirm |

## Provider readiness (boolean existence only — this agent environment)

| Credential / flag | Present |
| --- | --- |
| `FAL_KEY` | yes |
| `OPENAI_API_KEY` | no |
| `RUNWAYML_API_SECRET` / `NOVA_CREATIVE_VIDEO_API_KEY` | no |
| `DID_API_KEY` | no |
| `NOVA_CREATIVE_*_LIVE_ENABLED` (image/video/kling/voice/presenter) | no / off |
| `NOVA_CREATIVE_VIDEO_PROVIDER` | unset (defaults runway; fal key exists but live off) |

Production live flags were not mutated. Balance: **cannot_verify** from APIs; owner-reported −$3.16.

## Code fixes in this PR (non-billable)

| Area | Result | Notes |
| --- | --- | --- |
| 30s six-beat storyboard | PASS | Hook → Problem → Capabilities → Process → Progress → CTA (`getamicor.com`) |
| Local motion when video provider gated | PASS | Ken Burns MP4 per scene; not a still slideshow |
| Final promo refuse slideshow acceptance | PASS | Export / readiness mark stills as blocked |
| English captions + CTA fade on MP4 | PASS | ASS burn-in via bundled font; SRT sidecar fallback |
| Preflight quote + budget confirm | PASS | No purchase; paid confirm blocked when balance unverified/negative |
| UI defaults 30s / 9:16 vertical | PASS | Production preset + aspect + CTA defaults |
| Offline motion+caption MP4 smoke | PASS | `/opt/cursor/artifacts/nova-344-local-motion-captioned.mp4` (5s vertical proof) |
| Paid lip-sync / Whisper-aligned cues | BLOCKED | Requires funded live voice/lipsync after owner cost approval |
| Full 30s publish-ready commercial with consistent Genova lip sync | BLOCKED | Needs owner-approved credits + authenticated deploy verification |

## Tests run

- `tests/test_nova_creative_issue_344.py` — 7 passed
- `tests/test_presenter_media.py` + issue 344 — 14 passed
- `tests/test_nova_creative_issue_344.py` + `test_presenter_media.py` + `test_nova_creative_scene_jobs.py` — 32 passed
- Offline FFmpeg smoke: 720×1280 motion MP4 with burned captions / CTA fade

## Honest blockers

1. **No paid fal/Kling/D-ID/OpenAI generation** until owner funds and confirms per-project preflight.
2. **Authenticated production login / full 1–13 Studio walkthrough** not executed here (no credentials).
3. Local motion proves deliberate movement + caption/CTA pipeline, **not** provider lip-sync or a production Genova plate.
4. Deploy remains behind normal review/approval; this agent did not publish.
