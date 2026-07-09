"""Safe local reset: purge test rides/assignments/billing only; keep seeded users/drivers/providers."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import HealthISFDriver, HealthISFOrganization

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    with SessionLocal() as db:
        org = hs._get_or_create_default_org(db)
        hs.ensure_sample_driver_credentials(db, organization_id=str(org.id))
        summary = hs.purge_test_operational_artifacts(db, organization_id=str(org.id))
        drivers = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org.id)
            .order_by(HealthISFDriver.name.asc())
            .all()
        )
        summary["drivers"] = [
            {
                "id": d.id,
                "name": d.name,
                "status": str(d.status),
                "is_online": bool(d.is_online),
            }
            for d in drivers
            if d.name in {"James Smith", "Maria Garcia", "David Chen"} or str(d.phone or "").endswith("1001")
        ]
        if not summary["drivers"]:
            summary["drivers"] = [
                {
                    "id": d.id,
                    "name": d.name,
                    "status": str(d.status),
                    "is_online": bool(d.is_online),
                }
                for d in drivers[:5]
            ]
        summary["available_driver_count"] = sum(
            1 for d in drivers if str(d.status).lower() in {"available", "driverstatus.available"}
        )

    print("LOCAL_TEST_RESET", json.dumps(summary, indent=2, default=str))
    ok = (
        summary.get("dispatch_queue_count", 0) == 0
        and summary.get("active_assignments", 0) == 0
        and summary.get("available_driver_count", 0) >= 1
    )
    print(f"RESULT={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
