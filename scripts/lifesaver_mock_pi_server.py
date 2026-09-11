"""Local-only mock Home Hub server for Lifesaver V2 contract tests.

Binds 127.0.0.1 only. Does not contact real hardware, 911, or production.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi import FastAPI

from app.modules.lifesaver.hardware.mock_pi import router as mock_pi_router


def build_app() -> FastAPI:
    app = FastAPI(title="Lifesaver mock Pi", docs_url=None, redoc_url=None)
    app.include_router(mock_pi_router)
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_app(), host="127.0.0.1", port=8040, log_level="warning")
