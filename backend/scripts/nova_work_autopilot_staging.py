"""Explicit staging-only Work & Revenue scheduled discovery entrypoint.

Safe by default: configuration preflight happens BEFORE creating a database
engine or contacting any opportunity source. Do not add a Render cron until
the owner approves its exact staging service, cost, and verified identity.
"""
from __future__ import annotations

import json
import os
from app.core.nova.v3.scheduled_autopilot import inspect_configuration, run_staging_cycle


def main() -> int:
    config = {
        key: str(os.environ.get(key) or "") for key in (
            "APP_ENV", "AMICOR_ENVIRONMENT", "ENVIRONMENT",
            "NOVA_WORK_AUTOPILOT_STAGING_ENABLED",
            "NOVA_WORK_AUTOPILOT_APPROVED_DATABASE",
            "NOVA_WORK_AUTOPILOT_OWNER_ORG_ID",
            "NOVA_WORK_AUTOPILOT_OWNER_USER_ID",
        )
    }
    preflight = inspect_configuration(config)
    if preflight["status"] == "BLOCKED":
        print(json.dumps(preflight, sort_keys=True))
        return 0
    # This import is intentionally AFTER the staging-only fail-closed guard.
    from app.db.session import engine
    result = run_staging_cycle(engine, config=config)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
