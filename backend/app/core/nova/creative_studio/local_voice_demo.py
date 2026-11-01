"""Explicit local Kokoro bootstrap — no import-time model downloads.

Runs only when the owner intentionally executes this command after reviewing
the model license and local disk requirements. Never contacts paid APIs.
Usage: python -m app.core.nova.creative_studio.local_voice_demo --model-dir /path/to/preloaded/model --output /tmp/nova-voice.wav
"""
from __future__ import annotations
import argparse
from pathlib import Path

from .kokoro_local import KokoroLocalBackend
from .local_voice import VoiceNotReady, VoiceRequest
from .narration_qa import inspect_narration_wav
from .voice_readiness import check as check_voice_readiness


def run(*, model_dir: Path, output: Path) -> dict:
    if not model_dir.is_dir():
        raise VoiceNotReady("Preloaded local model directory is missing. No download attempted.")
    # Validate offline mode before importing libraries that could fetch weights.
    import os
    if os.environ.get("HF_HUB_OFFLINE") != "1" or os.environ.get("TRANSFORMERS_OFFLINE") != "1":
        raise VoiceNotReady(
            "Set HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1 before local inference."
        )
    readiness = check_voice_readiness(model_dir)
    if not readiness["ready_to_attempt_offline_inference"]:
        raise VoiceNotReady("Local Kokoro model files or runtime dependencies are missing or empty. No inference attempted.")
    try:
        from kokoro import KPipeline, KModel
        import torch
    except ImportError as exc:
        raise VoiceNotReady("Kokoro is not installed; install only after license/runtime review.") from exc
    # Explicit local paths avoid HF downloads and invalid repo_id lookups.
    model = KModel(repo_id="hexgrad/Kokoro-82M",
                   config=str(model_dir / "config.json"),
                   model=str(model_dir / "kokoro-v1_0.pth")).to("cpu").eval()
    pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", model=model, device="cpu")
    # Kokoro normally lazily fetches voices from HF. Preload only local voice.
    pipeline.voices["af_heart"] = torch.load(
        str(model_dir / "voices" / "af_heart.pt"), map_location="cpu", weights_only=True
    )
    script = "Welcome to AMICOR Nova, your AI business assistant."
    path = KokoroLocalBackend(pipeline).generate_wav(VoiceRequest(script), output)
    report = inspect_narration_wav(path)
    return {"audio_path": str(path), "duration_seconds": report.seconds,
            "quality_check": report.valid_for_narration}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(run(model_dir=args.model_dir, output=args.output))


if __name__ == "__main__":
    main()
