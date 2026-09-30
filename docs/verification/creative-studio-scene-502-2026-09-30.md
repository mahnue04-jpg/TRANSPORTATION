# Creative Studio step 8 investigation — September 30, 2026

The affected action is **8. Generate Next AI Scene**, `POST /api/nova/creative/projects/{project_id}/generate/video`.

## Findings

1. Step 8 still performed source-image generation, Runway submission/polling (90 seconds by default, plus requests with 45-second timeouts), video download (up to 120 seconds), and credit-exhaustion local encoding (up to 120 seconds) inside the original HTTP request. PR #218 only moved **Build Final Promo** into the background. Exception handlers returning 422 cannot catch a gateway-generated 502 or a killed process. This remaining synchronous path is a concrete timeout risk and explains why fixing final assembly did not address scene creation.
2. Resuming a pending Runway task created a new result asset but never replaced its earlier PROCESSING marker. Subsequent calls scanned the old marker and resumed the same task rather than advancing to the next storyboard scene.
3. Each fresh attempt regenerated source art even when usable artwork already existed. Retries therefore repeated image latency and potential charges.
4. FFmpeg used automatic thread counts for filtering/encoding. On a small Render instance this creates avoidable memory pressure. A production OOM event was **not** confirmed from server logs.

The live public Studio page was inspected and its step-8 label verified. The available browser was signed out; authenticated production requests and Render server logs were not available. The exact production 502 event is therefore not conclusively attributed to timeout versus process termination. The code defects above were independently verified.

## Changes

- Persist and return a QUEUED scene job immediately; perform generation in a background task with a separate database session.
- Poll the exact job ID every five seconds. Provider tasks that remain pending are checked automatically in the worker; completion/error is persisted and displayed.
- Duplicate clicks reconnect to an existing QUEUED/RUNNING job. Jobs stale for twenty minutes become retryable errors. The worker stops checking after fifteen minutes and preserves the provider task for a later retry.
- Replace a pending scene asset on completion instead of leaving a stale marker or creating duplicate rows.
- Reuse source artwork only when its prompt matches and its local file exists.
- Check provider availability before generating paid source art.
- Restrict FFmpeg decoder/filter/encoder threads to one for scene and final-promo encoding.
- Add backend and frontend regressions to Render backend diagnostic CI. Repair seven stale checks already failing on unchanged main; retain the provider-off/no-fake-URL and brand-safety assertions.

## Verification

- Backend Studio suites: **37 passed** (28 existing, 9 new).
- Frontend job polling: **3 passed**.
- ASGI proof: the HTTP response is delivered while a deliberately blocked generation worker is still running.
- Real FFmpeg smoke: a two-second 720×1280 MP4 was encoded and decoded; dimensions, duration, and a full frame were checked. No paid provider calls were made.
- Queue/completion persist across independent database sessions.
- Pending Runway task completes and the next call advances to scene 2 without generating another image for scene 1.
- Duplicate click, stale/interrupted job, ownership, missing storyboard, worker exception, retry artwork reuse, and frontend job correlation are covered.
- JavaScript syntax and git whitespace checks pass.

## Operational limits and deployment check

Background execution remains in the web process, consistent with the existing final-promo implementation. A restart interrupts execution; the database preserves job status and saved provider IDs, and a stale job can be retried after twenty minutes. Enqueue deduplication is designed for the current single-process Uvicorn service; multiple worker processes would require a database/distributed claim.

No deployment was requested or initiated by this investigation. After the owner deploys, verify on the owner's existing project: step 8 responds promptly; polling shows a persisted job; a real provider-backed scene becomes playable; the next click advances; and Render logs show no worker restart/OOM. Genuine Runway credit/configuration problems still need to be resolved with the provider. A local image-motion smoke test does not prove real AI generation works in production.
