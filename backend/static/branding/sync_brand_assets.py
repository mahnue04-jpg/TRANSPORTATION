"""Sync official Amicor brand assets into assets/branding (no redesign)."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_BRAND = ROOT.parents[2] / "assets" / "branding"

CANONICAL = [
    "amicor-official-source.png",
    "amicor-logo-full.png",
    "amicor-logo-primary.png",
    "amicor-mark.png",
    "amicor-logo.png",
    "apple-touch-icon.png",
    "android-chrome-192.png",
    "android-chrome-512.png",
    "favicon.ico",
    "brand.css",
    "brand.js",
]


def main() -> None:
    # Prefer regenerating from approved source when available.
    builder = ROOT / "build_official_assets.py"
    if builder.is_file() and (ROOT / "amicor-official-source.png").is_file():
        import runpy

        runpy.run_path(str(builder), run_name="__main__")

    REPO_BRAND.mkdir(parents=True, exist_ok=True)
    for name in CANONICAL:
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, REPO_BRAND / name)
    print(f"Brand assets synced: {ROOT} -> {REPO_BRAND}")


if __name__ == "__main__":
    main()
