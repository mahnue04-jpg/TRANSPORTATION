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


def run(*, model_dir: Path, output: Path) -> dict:
    if not model_dir.is_dir():
        raise VoiceNotReady("Preloaded local model directory is missing. No download attempted.")
    # Validate offline mode before importing libraries that could fetch weights.
    import os
    if os.environ.get("HF_HUB_OFFLINE") != "1" or os.environ.get("TRANSFORMERS_OFFLINE") != "1":
        raise VoiceNotReady(
            "Set HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1 before local inference."
        )
    try:
        from kokoro import KPipeline
    except ImportError as exc:
        raise VoiceNotReady("Kokoro is not installed; install only after license/runtime review.") from exc
    pipeline = KPipeline(lang_code="a", repo_id=str(model_dir))
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
