"""Resolve the canonical application release version for startup and health probes."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_RELEASE_FILE = Path(__file__).resolve().parents[2] / "release.version"


@lru_cache(maxsize=1)
def resolve_app_version() -> str:
    """Return the release tag surfaced in startup logs and health checks.

    Priority:
      1. ``backend/release.version`` shipped with the deploy artifact
      2. ``APP_VERSION`` environment variable (Render dashboard / compose)
      3. ``dev``
    """
    if _RELEASE_FILE.is_file():
        file_version = _RELEASE_FILE.read_text(encoding="utf-8").strip()
        if file_version:
            return file_version

    env_version = os.environ.get("APP_VERSION", "").strip()
    if env_version:
        return env_version

    return "dev"
