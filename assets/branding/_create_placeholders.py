"""DISABLED — temporary Brand Identity v1 placeholders must not be regenerated.

Canonical artwork: backend/static/branding/amicor-official-source.png
Rebuild with: backend/static/branding/build_official_assets.py
"""
from __future__ import annotations

import sys


def main() -> None:
    print(
        "Refusing to create temporary placeholder logos.\n"
        "Use backend/static/branding/build_official_assets.py with "
        "amicor-official-source.png instead.",
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    main()
