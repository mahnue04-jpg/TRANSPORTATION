"""Loads the isolated Home Hub agent package without touching frozen products."""
from __future__ import annotations

import sys
from pathlib import Path


def agent_root() -> Path:
    return Path(__file__).resolve().parents[5] / "hardware" / "lifesaver-home-hub"


def ensure_agent_path() -> Path:
    root = agent_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def agent_router():
    ensure_agent_path()
    from lifesaver_home_hub.app import router

    return router


def emulator():
    ensure_agent_path()
    from lifesaver_home_hub.emulator import get_emulator

    return get_emulator()
