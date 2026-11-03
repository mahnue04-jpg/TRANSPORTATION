"""Owner-invoked Kokoro model acquisition. Never run on import, CI, or production.

Dry-run by default. Explicit --download is required for a network request.
Downloads only official Kokoro config, weights and chosen voice to a fresh
local directory. No paid APIs, automatic retries, or deployment.
"""
from __future__ import annotations

import argparse
from pathlib import Path

REPOSITORY = "hexgrad/Kokoro-82M"
FILES = ("config.json", "kokoro-v1_0.pth", "voices/af_heart.pt")


def acquire(*, destination: Path, download: bool = False, revision: str | None = None) -> dict:
    destination = destination.expanduser().resolve()
    plan = {"repository": REPOSITORY, "destination": str(destination),
            "files": list(FILES), "revision": revision, "downloaded": False}
    if not download:
        return plan
    if revision is None:
        raise ValueError("Specify --revision with a reviewed commit hash for reproducibility.")
    if not (len(revision) == 40 and all(c in "0123456789abcdef" for c in revision.lower())):
        raise ValueError("--revision must be a full 40-character commit SHA.")
    if destination.exists():
        raise FileExistsError("Destination must not exist; refusing to mix or overwrite model assets.")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("Install huggingface_hub in an isolated environment first.") from exc

    snapshot_download(repo_id=REPOSITORY, repo_type="model", revision=revision,
                      allow_patterns=list(FILES), local_dir=str(destination))
    missing = [filename for filename in FILES
               if not (destination / filename).is_file()
               or (destination / filename).stat().st_size == 0]
    if missing:
        raise RuntimeError(f"Download incomplete: {', '.join(missing)}")
    plan["downloaded"] = True
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--revision", help="Reviewed upstream model commit (40 hex characters)")
    parser.add_argument("--download", action="store_true", help="Explicitly permit official model download")
    args = parser.parse_args()
    print(acquire(destination=args.destination, revision=args.revision, download=args.download))
