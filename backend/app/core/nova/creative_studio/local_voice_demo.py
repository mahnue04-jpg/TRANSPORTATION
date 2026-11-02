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


def run(*, model_dir: Path, output: Path, script: str | None = None,
        speed: float = 1.0, verify_model: bool = False) -> dict:
    request = VoiceRequest(
        "Welcome to AMICOR Nova, your AI business assistant." if script is None else script,
        speed=speed,
    )
    request.validate()
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
    if verify_model:
        import hashlib
        reviewed = {
            "kokoro-v1_0.pth": "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4",
            "config.json": "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f",
            "voices/af_heart.pt": "0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff",
        }
        for filename, expected in reviewed.items():
            digest = hashlib.sha256()
            with (model_dir / filename).open("rb") as model_file:
                for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise VoiceNotReady("Local asset checksum does not match the reviewed Kokoro profile.")
    try:
        from kokoro import KPipeline, KModel
        import torch
    except ImportError as exc:
        raise VoiceNotReady("Kokoro is not installed; install only after license/runtime review.") from exc
    try:
        # Supply every asset explicitly: do not let the model or pipeline
        # resolve weights or the voice through the network.
        model = KModel(
            repo_id="hexgrad/Kokoro-82M",
            config=str(model_dir / "config.json"),
            model=str(model_dir / "kokoro-v1_0.pth"),
        ).to("cpu").eval()
        pipeline = KPipeline(
            lang_code="a", repo_id="hexgrad/Kokoro-82M",
            model=model, device="cpu",
        )
        pipeline.voices["af_heart"] = torch.load(
            str(model_dir / "voices" / "af_heart.pt"),
            map_location="cpu", weights_only=True,
        )
    except Exception as exc:
        raise VoiceNotReady(
            "Local Kokoro model initialization failed. Check model/runtime compatibility; no paid fallback attempted."
        ) from exc
    path = KokoroLocalBackend(pipeline).generate_wav(request, output)
    report = inspect_narration_wav(path, max_seconds=120)
    return {"audio_path": str(path), "duration_seconds": report.seconds,
            "quality_check": report.valid_for_narration}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--script-file", type=Path)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--verify-model", action="store_true")
    args = parser.parse_args()
    # This command runs in a dedicated child, never the web process. Block
    # Python socket connections before importing model libraries.
    import socket
    def no_network(*_args, **_kwargs):
        raise VoiceNotReady("Network connections are disabled in the local voice worker.")
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    socket.create_connection = no_network
    import json
    script = args.script_file.read_text(encoding="utf-8") if args.script_file else None
    print(json.dumps(run(model_dir=args.model_dir, output=args.output, script=script,
                         speed=args.speed, verify_model=args.verify_model)))


if __name__ == "__main__":
    main()
