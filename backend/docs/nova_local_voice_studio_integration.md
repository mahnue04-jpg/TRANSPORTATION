# Nova local voice: Studio backend integration

Status: implemented in draft PR #425; not merged or deployed. The original approved 30-second commercial and its soundtrack are unchanged.

## Behavior

The existing Studio Generate Voice service now has an explicit local provider selection. With no selector, existing OpenAI behavior remains unchanged. With `NOVA_CREATIVE_VOICE_PROVIDER=nova_local`, voice requests use the local adapter; failure never falls back to OpenAI. Unknown selectors fail closed.

The local provider runs a CPU child process with the reviewed Kokoro model, config and af_heart voice checksums, the owner-approved pronunciation mapping, and speed 0.87. Scripts remain unchanged in stored records and captions. Local generation writes a unique WAV in the existing Studio media directory; the service can save its URL and provenance as an audio asset. Existing owner-scoped download handling supports WAV.

The local provider supports the general Generate Voice action. Generate Presenter Voice is deliberately held: word-timed caption alignment and lip-sync integration are not yet connected. It does not pretend that OpenAI voice names such as coral are the local stock voice.

## Test-host prerequisites

These are configuration instructions for a separately validated development/test host, not authorization to change production infrastructure:

```text
NOVA_CREATIVE_VOICE_PROVIDER=nova_local
NOVA_LOCAL_VOICE_ENABLED=true
NOVA_LOCAL_VOICE_MODEL_DIR=/absolute/path/to/preloaded/kokoro
```

Use a provisioned Python environment with Kokoro 0.9.4, PyTorch 2.6.0+cpu, and the English en_core_web_sm package. Provision dependencies and the three reviewed model assets before running the web service. Runtime imports never install missing dependencies or download weights.

The runner supports `--script-file`, `--speed`, and `--verify-model`. The provider always requests checksum verification and starts the child with HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1. Its CLI blocks Python socket connections before model imports. This is application-level isolation, not an OS network sandbox.

Generation requires at least 2304 MiB free before admission. A shared file lock prevents concurrent local voice workers on the same host/media volume. The parent monitors memory and kills/reaps the child if free memory falls below 256 MiB or the 120-second timeout expires. A worker can publish a WAV only after format/duration/signal validation. Partial and failed files are removed; locks release on exit.

## Verified

- 46 isolated voice/provider checks passed locally, including the exact workflow commands.
- A real full-commercial request completed through NovaLocalVoiceProvider, its subprocess runner, WAV validation and atomic save: 28.0 seconds at 24 kHz, speed 0.87, no paid calls. Saved WAV SHA-256 matched returned provenance.
- The first real provider attempt correctly refused admission when free memory was insufficient. After releasing optional filesystem cache from this task's runtime files, a fresh attempt passed without lowering the admission threshold.
- The earlier approved 30-second narration remains separate from this fresh engineering test output. New generated audio still requires review.

## Remaining

Deploy to an approved test environment and verify authenticated Studio generation, persisted asset playback/download, cross-owner isolation and interrupted-job recovery. Resource capacity, pinned dependency provisioning, presenter word alignment and production rollout remain separate work. Do not enable this provider on the existing small production service solely because contract tests passed.
