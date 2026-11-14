"""Proposed non-mutating startup entrypoint for isolated Growth Agent staging.

NOT connected to Render. Deployment requires separate owner approval, a tested
database backup restore and an exact reviewed commit/DB identity configuration.
No alembic, pytest, SQL, or provider calls are made by this launcher.
"""
from __future__ import annotations

import os
import sys

from app.core.nova.growth_agent.staging_preflight import validate


def build_uvicorn_argv(environment: dict[str, str]) -> list[str]:
    """Validate without side effects, then construct a fixed local server command."""
    ok, reason = validate(environment)
    if not ok:
        raise ValueError(reason)
    port = environment.get("PORT", "").strip()
    if not port.isascii() or not port.isdecimal() or not (1 <= int(port) <= 65535):
        raise ValueError("Invalid or missing service PORT")
    return [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "0.0.0.0", "--port", port, "--workers", "1",
    ]


def main() -> int:
    try:
        argv = build_uvicorn_argv(dict(os.environ))
    except ValueError as exc:
        # Messages returned by validate never contain credentials.
        print(str(exc), file=sys.stderr)
        return 1
    print("Staging preflight passed; starting app without migration or test commands")
    os.execv(sys.executable, argv)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
