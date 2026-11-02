# Nova local voice: Studio backend integration

Status: implemented in draft PR #425 and verified on the temporary Render validation host; not merged or activated in production. The original approved 30-second commercial and its soundtrack are unchanged.

## Behavior

The existing Studio Generate Voice service now has an explicit local provider selection. With no selector, existing OpenAI behavior remains unchanged. With `NOVA_CREATIVE_VOICE_PROVIDER=nova_local`, voice requests use the local adapter; failure never falls back to OpenAI. Unknown selectors fail closed.

The local provider runs a standalone CPU child process with the reviewed Kokoro model, config and af_heart voice checksums, the owner-approved pronunciation mapping, and speed 0.87. Scripts remain unchanged in stored records and captions. Local generation writes a unique WAV in the existing Studio media directory; the service can save its URL and provenance as an audio asset. Existing owner-scoped download handling supports WAV.

The local provider supports the general Generate Voice action. Generate Presenter Voice is deliberately held: word-timed caption alignment and lip-sync integration are not yet connected. It does not pretend that OpenAI voice names such as coral are the local stock voice.

## Test-host prerequisites

These are configuration instructions for a separately validated development/test host, not authorization to change production infrastructure:

```text
NOVA_CREATIVE_VOICE_PROVIDER=nova_local
NOVA_LOCAL_VOICE_ENABLED=true
NOVA_LOCAL_VOICE_MODEL_DIR=/absolute/path/to/preloaded/kokoro
```

Use a provisioned Python environment with Kokoro 0.9.4, PyTorch 2.6.0+cpu, and the English en_core_web_sm package. Provision dependencies and the three reviewed model assets before running the web service. Runtime imports never install missing dependencies or download weights.

The standalone `local_voice_worker.py` entry point avoids the web package initializers. Its runner supports `--script-file`, `--speed`, and `--verify-model`. Linux parent-death protection stops a child when its web parent disappears, including a startup-parent identity check. The provider always requests checksum verification and starts the child with HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1. Its CLI blocks Python socket connections before model imports. This is application-level isolation, not an OS network sandbox.

Generation requires at least 2304 MiB available headroom before admission. Cgroup accounting includes reclaimable inactive file cache, but does not count anonymous model memory or active file pages as available. A shared file lock prevents concurrent local voice workers on the same host/media volume. The parent monitors memory and kills/reaps the child if free memory falls below 256 MiB or the 120-second timeout expires. A worker can publish a WAV only after format/duration/signal validation. Partial and failed files are removed; locks release on exit.

## Verified

- 50 isolated voice/provider checks passed locally, including the exact workflow commands.
- 72 API/core checks passed locally (11 new API cases plus 61 existing Studio checks). They cover SQLite session reopen, owner-scoped WAV read/download, missing authentication, real signed JWTs, tampered/revoked tokens, another owner, paid-budget guard retention, failed generation, blocked jobs and interrupted-job recovery. API fixture workers are synthetic; the real-model proof below is separate.
- A real full-commercial request completed through NovaLocalVoiceProvider, its subprocess runner, WAV validation and atomic save: 28.0 seconds at 24 kHz, speed 0.87, no paid calls. Saved WAV SHA-256 matched returned provenance.
- The first real provider attempt correctly refused admission when free memory was insufficient. After releasing optional filesystem cache from this task's runtime files, a fresh attempt passed without lowering the admission threshold.
- The earlier approved 30-second narration remains separate from this fresh engineering test output. New generated audio still requires review.

## API integration and recovery

The basic voice route applies the paid budget guard only to non-local generation. Short drama and external provider budget checks remain in place. Local jobs persist their provider before inference; polling an expired RUNNING local job after 180 seconds records ERROR without invoking a provider. Disabled/missing-model results are terminal so clients do not poll forever.

A real-model request passed through the actual Studio routes, service and standalone local worker. It saved a 28.0-second, 24 kHz WAV and downloaded 1,344,044 matching bytes; another owner received 404. This manual proof substituted the identity dependency and used an in-memory store. Real JWT enforcement and SQLite reopen were separately verified by the API regressions. No paid calls or publication occurred.

The broader backend diagnostic initially hit a Chrome rendering-test timeout and passed on a targeted retry. That was not a voice-model failure.

## Remaining

The approved 4 GB validation-host browser test passed as recorded below. Presenter word alignment, production dependency provisioning, capacity planning and production rollout remain separate work. Do not enable this provider on the existing small production service solely because the temporary test passed.


## Temporary Render test package

`Dockerfile.nova-voice-test` is a separate Python 3.12/Linux CPU image. It adds the pinned top-level speech runtime requirements from `requirements-nova-voice-test.txt`, preloads the reviewed model revision during build, verifies all three asset checksums, and enables offline local voice only at runtime. The normal production Dockerfile and requirements are not replaced.

The test startup command refuses every hostname except the approved validation hostname, rejects non-local voice selection and refuses enabled paid-provider/live-billing flags. Render environment overrides must be checked before deployment because they override image defaults. The Dockerfile-specific test ignore file excludes credentials, local databases and caches while preserving application/media source assets.

Validation: the combined base/speech dependency resolver dry run passed. Render built and ran the image successfully. All 14 startup checks passed, including an explicit single-worker override of Render's WEB_CONCURRENCY=2 default. When an environment uses ephemeral signing keys, multiple web workers can generate different keys and reject one another's sessions. The test launcher now explicitly uses one web worker. Sessions can still require renewal after restart; production needs a stable secret managed separately.

## Signed-in browser proof

The image ran on an approved temporary validation host. All four GitHub workflows passed for the tested code. The browser signed in through the secure credential flow and successfully saved the brief and text-only script in an isolated test project.

The normal **9. Generate Voice** button generated and saved local stock-voice narration. Generation completed in approximately 24 seconds. The output is a 21.7-second, mono, 24 kHz WAV, 1,041,644 bytes. The authenticated browser download checksum matched provider provenance exactly.

The browser audio element reported readyState 4 and no media error, played to currentTime 21.7 with ended=true, and loaded the same saved asset successfully after a page reload. No paid-provider calls or publication occurred. This proves the general local-narration browser path, not presenter lip-sync or approval of the synthetic test script. The approved commercial was not regenerated or replaced.

Restoration was verified after the test: the original application, source/build settings, compute allocation, automatic-deployment setting and existing persistent disk were restored. No environment variables were changed.

Observed validation-host baseline before any proposed test change:

- Compute: 1c-2g (2 GB RAM); idle measured usage approximately 460 MiB. The current model plus web process does not fit the admission/reserve policy.
- Capture the current source branch and live revision privately before testing.
- Docker context: `backend`; Dockerfile: `backend/Dockerfile`; automatic deploys off.
- Existing persistent disk: 10 GB mounted at `/data`. Do not resize or replace it for this test.

Before a paid test, capture a fresh configuration snapshot and record the authorized spending/time limit. A suitable proposed runtime is 2c-4g. Restore the previous compute plan, source/build settings and any changed non-secret flags after testing or failure. Preserve databases and media. Verify the restored live deployment and memory limit before reporting completion. A service with an attached disk can be briefly unavailable during redeploys.
