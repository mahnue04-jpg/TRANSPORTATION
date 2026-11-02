# Nova local voice: Studio backend integration

Status: implemented in draft PR #425 and verified on the temporary Render validation host; not merged or activated in production. The original approved 30-second commercial and its soundtrack are unchanged.

## Behavior

The latest short pronunciation sample was explicitly approved by the owner. Future local narration maps the written brand to the literal audio-only wording `Amih-core`, replacing the earlier phoneme override. Stored scripts and captions retain AMICOR. The existing approved commercial is unchanged. This pronunciation update is prepared in the draft branch; it has not been activated in production.

The existing Studio Generate Voice service now has an explicit local provider selection. With no selector, existing OpenAI behavior remains unchanged. With `NOVA_CREATIVE_VOICE_PROVIDER=nova_local`, voice requests use the local adapter; failure never falls back to OpenAI. Unknown selectors fail closed.

The local provider runs a standalone CPU child process with the reviewed Kokoro model, config and af_heart voice checksums, the owner-approved pronunciation mapping, and speed 0.87. Scripts remain unchanged in stored records and captions. Local generation writes a unique WAV in the existing Studio media directory; the service can save its URL and provenance as an audio asset. Existing owner-scoped download handling supports WAV.

The local provider supports Generate Voice and Generate Presenter Voice. When the local provider is selected, the presenter selector offers the approved local stock voice and disables external voice names. Presenter narration requires explicit af_heart selection and complete validated native caption timing; missing timing does not publish an audio file. Switching back to the external provider removes the local option, and the external adapter refuses af_heart rather than substituting another voice.

Local presenter narration retains the approved PCM without re-encoding or claiming LUFS normalization. Its metadata records the measured peak, caption preparation version and presenter_narration_ready=true, while presenter_alignment and publish_ready remain false. Preparing narration does not generate a talking face. Paid lip-sync/motion routes retain their budget checks. The voice endpoint skips a paid quote only when the selected provider is local; external speech and short drama keep the existing budget guard.

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

The approved 4 GB general-narration browser test passed as recorded below. The newer native-caption and presenter-narration changes have separate local proof and have not been deployed. Live browser validation of the new presenter controls, lip-sync renderer integration, production dependency provisioning, capacity planning and production rollout remain separate work. Do not enable this provider on the existing small production service solely because the temporary test passed.

## Native caption timing

The worker can export Kokoro token times with the exact concatenated PCM offsets, avoiding separate transcription. An exact normalized match maps audio-only brand/domain expansions back to the unchanged written script. Missing, nonfinite, overlapping, out-of-range or mismatched timing never becomes aligned caption metadata. Only native frame rounding within 75 ms can be clipped to the PCM boundary; word times are never evenly estimated.

The parent validates the WAV checksum, exact script checksum, duration, complete written-word coverage and monotonic timing before rebuilding caption cues. It ignores child-supplied caption text. Invalid or absent timing preserves reviewable audio but returns caption_alignment=false without a paid fallback. Valid cues are stored in provider_result for the existing final-promo caption path. Presenter/lip-sync readiness remains false.

Local verification: 72 isolated checks passed, plus 86 API/core/startup checks. Coverage includes brand/domain expansions, multi-chunk PCM offsets, missing/extra words, invalid times, mismatched recording/script fingerprints, native-metadata persistence through SQLite reopen and protected downloads. A real reviewed-model full narration run at speed 0.87 produced 27.775 seconds, 58 written words and 10 caption cues, including the unchanged AMICOR and GetAmiCore.com text. A short real-model run also passed. These are timing and format checks; new full narration still requires owner listening review.

## Presenter narration connection

Subsequent verification passed 75 isolated checks, 97 API/core/startup/presenter-media checks and 11 frontend checks. The API cases cover the presenter endpoint's local voice selection, exact-script captions, persisted readiness metadata, cross-owner rejection, refusal to alias an external voice and preservation of the external paid-budget guard. Frontend cases verify provider switching and that disabled/failed narration displays the actual provider reason instead of a success banner.

The parent now verifies native timing against exact PCM frame duration instead of the public millisecond-rounded duration report. A fractional-frame-duration regression covers recordings whose rounded display length differs from their exact length.

A separate real-provider invocation using the reviewed local model and full script returned presenter_narration_ready=true and caption_alignment=true: 27.775 seconds, measured peak fraction 0.5162, no paid calls, no re-encoding and no lip-sync/publishing claim. This real-model proof invoked the provider directly; endpoint authentication and persistence were tested separately with a synthetic worker. Existing approved commercial assets and hosting configuration were not changed.


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
