#!/usr/bin/env python3
"""Diagnostic Uvicorn entrypoint for disposable receptionist staging only.

Preserve the standard Uvicorn startup path while keeping Python's faulthandler
armed across app import and ASGI lifespan startup. Stack traces show source
locations, not environment variables or configured secrets. No data changes.
"""

from __future__ import annotations

import faulthandler
import os
import sys

TRACE_AFTER_SECONDS = 120


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    faulthandler.enable(file=sys.stderr)
    faulthandler.dump_traceback_later(
        TRACE_AFTER_SECONDS, repeat=True, file=sys.stderr
    )
    # Executed by filename from backend/scripts, so sys.path[0] is scripts.
    # Uvicorn must resolve app.main from the backend package root.
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    print("[receptionist-staging-uvicorn] loading ASGI application", flush=True)
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
