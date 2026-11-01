"""Read-only local readiness diagnostic; no network, downloads or inference."""
from __future__ import annotations
import argparse
import importlib.util
from pathlib import Path


def check(model_dir: Path) -> dict:
    files = sorted(p.name for p in model_dir.iterdir()) if model_dir.is_dir() else []
    return {
        "model_directory_exists": model_dir.is_dir(),
        "model_directory_nonempty": bool(files),
        "kokoro_package_installed": importlib.util.find_spec("kokoro") is not None,
        "torch_installed": importlib.util.find_spec("torch") is not None,
        "model_files": files[:20],
        "ready_to_attempt_offline_inference": bool(files)
        and importlib.util.find_spec("kokoro") is not None,
        "notes": "No download or inference performed. Human license and quality review still required.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    print(check(parser.parse_args().model_dir))
