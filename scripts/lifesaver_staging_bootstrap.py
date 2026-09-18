#!/usr/bin/env python3
"""Initialize a dedicated Lifesaver staging database.

Creates missing lifesaver_* tables via ensure_lifesaver_schema().
Does not run alembic upgrade heads.
Does not use production Health ISF credentials.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main() -> int:
    os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")
    from app.modules.lifesaver.staging import (
        initialize_isolated_staging_runtime,
        looks_like_production_database,
        refuse_alembic_heads,
        validate_isolated_runtime,
    )

    try:
        refuse_alembic_heads(sys.argv)
    except RuntimeError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    if looks_like_production_database():
        print("REFUSED: DATABASE_URL looks like the Health ISF production database.", file=sys.stderr)
        return 2

    errors = validate_isolated_runtime()
    if errors:
        print("REFUSED: " + " ".join(errors), file=sys.stderr)
        return 2

    created = initialize_isolated_staging_runtime()
    print("OK: lifesaver schema ready")
    print("auth_tables=" + ",".join(created["auth_tables"]))
    print("tables=" + ",".join(created["lifesaver_tables"]))
    print("alembic_heads=not_run")
    print("health_isf_schema=not_run")
    print("nova_schema=not_run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
