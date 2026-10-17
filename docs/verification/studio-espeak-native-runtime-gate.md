# Creative Studio offline narration: release verification

The application requires the **native** `espeak-ng` executable and voice data. Installing a Python wrapper alone is insufficient. The existing Render service `srv-d8v1bl1kh4rs73d54lh0` is a **Python** service with a persistent disk at `/data/onboarding_docs`, not a Docker service. Adding `backend/Dockerfile` does not install anything in that running service.

## Required checks before activation

1. Build and run the new Docker image in an isolated test environment; do not reconfigure or redeploy the existing Starter service as part of this PR.
2. Execute `command -v espeak-ng` and `espeak-ng --voices` in the running image. Generate a WAV with `espeak-ng -w /tmp/studio-smoke.wav 'Studio test narration'` and verify a nonempty WAV.
3. Verify the existing MP4 engine, code startup, and `/static/nova-creative/index.html` over HTTPS.
4. In a **nonproduction, authorized, authenticated** tenant, create a NEW project with storyboard, run the offline montage, poll to terminal state, play and download the MP4. Verify isolation with a second user and durable storage after restart.
5. Review voice-tool licensing and the generated media's commercial rights. Until cleared, generated media is preview-only and must not be offered as a publish-ready product.
6. Compare environment and persistent disk bindings before proposing a host migration; keep the owner-approved 60-second demo and production secrets/data unchanged.

## Known live reproduction

On October 16 the owner-authorized Studio browser created `cproj_eadc72d001ca` (AMICOR Second Commercial), generated a script and six-scene storyboard, then received `LOCAL_NARRATION_UNAVAILABLE` because `espeak-ng` is missing. A separate final-promo job showed PROCESSING, not a verified downloadable MP4.

**Release gate:** no merge, production runtime change, provider spend or publish-ready claim until the above evidence is recorded.
