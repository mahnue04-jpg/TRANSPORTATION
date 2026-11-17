#!/usr/bin/env python3
"""Standalone, guarded staging diagnostic boot path.

This is an alternative start entrypoint for the isolated Nova receptionist
staging service. The existing bootstrap file is deliberately not modified.
It reuses the exact pinned-commit, destination, advisory lock, and Alembic
checks from receptionist_staging_start.migrate_only(), before starting the
diagnostic Uvicorn process. No production or provider configuration changes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    import receptionist_staging_start as existing

    print("[receptionist-diag-bootstrap] running existing guarded migration checks", flush=True)
    existing.migrate_only()
    script = Path(__file__).resolve().with_name("receptionist_uvicorn_diagnostic.py")
    if not script.is_file():
        raise RuntimeError("diagnostic Uvicorn entrypoint missing")
    print("[receptionist-diag-bootstrap] migration verified; launching traced Uvicorn", flush=True)
    os.chdir(str(existing._backend_dir()))
    os.execv(sys.executable, [sys.executable, "-u", str(script)])


if __name__ == "__main__":
    main()
