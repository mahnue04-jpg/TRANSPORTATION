# First genuine Nova voice sample — operator runbook

**Status: NOT RUN.** Run only on an isolated, network-connected developer computer. No GitHub Actions install, Render deploy, paid voice provider, or automatic production activation.

## Preflight
1. Review https://huggingface.co/hexgrad/Kokoro-82M (Apache-2.0 model card) and https://github.com/hexgrad/kokoro; review dependencies and voice asset terms before commercial use.
2. Record a **full, reviewed 40-character commit SHA** for the model. Do not use `main` as a revision.
3. Create a disposable Python 3.11 virtual environment and install vetted/pinned Kokoro, PyTorch, and huggingface_hub dependencies. Document actual versions and platform requirements.
4. Ensure sufficient disk/RAM, choose a fresh destination outside the code repository, and never use AMICOR's production Render service.

## Explicit model acquisition

From the repository root, after the above checks:

```sh
python backend/app/core/nova/creative_studio/acquire_kokoro.py --destination /tmp/amicor-kokoro --revision <FULL_REVIEWED_COMMIT_SHA>
# Dry run only: prints plan, does not download.
python backend/app/core/nova/creative_studio/acquire_kokoro.py --destination /tmp/amicor-kokoro --revision <FULL_REVIEWED_COMMIT_SHA> --download
```

`--download` is an explicit network action. The helper refuses existing destination directories. The directory contains official model configuration, weights and `voices/af_heart.pt` after a successful run.

## Offline runtime

After all files are locally present, from `backend/` in the isolated environment:

```sh
python app/core/nova/creative_studio/voice_readiness.py --model-dir /tmp/amicor-kokoro
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m app.core.nova.creative_studio.local_voice_demo --model-dir /tmp/amicor-kokoro --output /tmp/amicor-nova-first.wav
```

Listen to the resulting WAV. Expected speech: "Welcome to AMICOR Nova, your AI business assistant." Pronunciation target: "Ammy Core Nova"; written branding remains AMICOR. Verify duration, listening quality, model revision, resource consumption and no network access during inference.

**Important:** Kokoro runtime compatibility and any dependency-side attempts to access the network remain unverified with real weights. Offline environment flags alone are not a network sandbox; for a strict test block outbound network access at the OS/container layer. Do not deploy or publish a sample until independently reviewed. Do not claim a real audio sample exists until the file was actually generated and listened to.
