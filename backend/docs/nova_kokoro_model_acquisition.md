# Kokoro model acquisition gate — Nova Voice Engine

Status: **model not acquired or installed**. Research only, no GPU purchase, no production activation.

## Verified upstream
- Canonical model repository: https://huggingface.co/hexgrad/Kokoro-82M
- Upstream source code: https://github.com/hexgrad/kokoro
- Model card license: Apache-2.0. Validate attribution and dependency/voice licenses before commercialization.
- Official repo tree advertises about 363 MB for its main snapshot, including `kokoro-v1_0.pth` (~327 MB). Exact downloaded footprint depends on chosen files and dependency caches.

## Controlled acquisition procedure (requires explicit permission for download)
1. Choose a disposable development machine with sufficient disk/RAM; do not use the live Render application or its small persistent disk.
2. Review upstream model card and dependencies, pin a trusted revision and record checksums.
3. Obtain only required weights/config/voice files from official Hugging Face sources; do not use lookalike Kokoro websites.
4. Install the runtime into an isolated virtual environment; validate sample rate, pronunciation and audio quality.
5. Set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` for runtime. No implicit network/model downloads during inference.
6. Run local readiness diagnostics, then the explicit local demo runner. Save produced audio only to a development output directory.
7. Human approval required before any production integration or provider fallback.

## Acceptance
- Playable real model-generated WAV for "Welcome to AMICOR Nova, your AI business assistant."
- Spoken brand sounds "Ammy Core"; captions remain "AMICOR Nova."
- Record runtime seconds, CPU/RAM usage, model revision, and actual disk footprint.
- Fail without audio on missing models/dependencies. Never label synthetic test samples as real voice.
- No paid services, top-ups, extra subscription or deployment without separate owner approval.

## Caveats
The current code is not a guarantee that the upstream KPipeline supports arbitrary local `repo_id` paths across versions. Validate this first; modify adapter only after concrete runtime failure evidence.
