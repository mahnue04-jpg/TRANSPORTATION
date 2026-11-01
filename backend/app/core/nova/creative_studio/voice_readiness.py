"""Read-only Kokoro model readiness checks; never download or run inference."""
from __future__ import annotations
import argparse
import importlib.util
from pathlib import Path

REQUIRED_FILES = ("config.json", "kokoro-v1_0.pth", "voices/af_heart.pt")


def check(model_dir: Path) -> dict:
    exists = model_dir.is_dir()
    files = sorted(p.name for p in model_dir.iterdir()) if exists else []
    missing = [name for name in REQUIRED_FILES if not (model_dir / name).is_file()]
    empty = [name for name in REQUIRED_FILES if (model_dir / name).is_file()
             and (model_dir / name).stat().st_size == 0]
    kokoro_installed = importlib.util.find_spec("kokoro") is not None
    torch_installed = importlib.util.find_spec("torch") is not None
    return {
        "model_directory_exists": exists,
        "model_directory_nonempty": bool(files),
        "kokoro_package_installed": kokoro_installed,
        "torch_installed": torch_installed,
        "model_files": files[:20],
        "missing_required_files": missing,
        "empty_required_files": empty,
        "ready_to_attempt_offline_inference": exists and not missing and not empty
            and kokoro_installed and torch_installed,
        "notes": "File-presence check only. Does not verify weights, model compatibility, licensing, or audio quality. No network/inference used.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    print(check(parser.parse_args().model_dir))
