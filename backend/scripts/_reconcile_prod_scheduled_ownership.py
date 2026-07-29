"""Run scheduled reservation ownership reconciliation on production (read/heal only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND = SCRIPT_DIR.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import production_auth as pa

BASE = pa.BASE
ORG_ID = "308dc05a-6781-4ef7-91fc-ff22606937e3"


def main() -> int:
    tokens = pa.resolve_production_tokens()
    headers = {"Authorization": f"Bearer {tokens['dispatcher_token']}"}
    resp = requests.get(
        f"{BASE}/api/health-isf/dispatch/queue",
        headers=headers,
        params={"organization_id": ORG_ID, "force_maintenance": "true", "limit": 1},
        timeout=300,
    )
    print(f"status={resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:3000]}
    print(json.dumps(body, indent=2, default=str))
    return 0 if resp.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
