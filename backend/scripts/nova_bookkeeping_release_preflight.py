"""Safe, offline release-readiness report for Nova accounting.

Run from backend:
  PYTHONPATH=. python scripts/nova_bookkeeping_release_preflight.py

This is deliberately NOT a Render inspector or a deployment tool. It never
imports cloud credentials or creates database/S3 clients. The report lists
missing evidence rather than treating synthetic CI checks as authorization.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.core.nova.work_revenue.bookkeeping_staging_preflight import (
    inspect_staging_readiness,
)

# Only use explicitly allowlisted non-secret configuration. Never copy or
# print arbitrary env vars; database URLs, API tokens and S3 keys are excluded.
SAFE_CONFIG = (
    "APP_ENV",
    "AMICOR_ENVIRONMENT",
    "ENVIRONMENT",
    "NOVA_BOOKKEEPING_DURABLE_ENABLED",
    "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
    "PLATFORM_OPS_DOCUMENT_STORAGE",
)
MAX_PATH = 250


def build_report(environ: dict[str, str]) -> dict:
    config = {key: str(environ.get(key, "")) for key in SAFE_CONFIG}
    # No engine, S3 client, approval decision, or forged signed consent is
    # supplied. Results MUST remain blocked, including in CI.
    result = inspect_staging_readiness(config=config)
    result["report_kind"] = "NOVA_BOOKKEEPING_OFFLINE_RELEASE_PREFLIGHT"
    result["run_mode"] = "NO_EXTERNAL_CONNECTIONS"
    result["synthetic_ci_is_customer_proof"] = False
    result["real_render_staging_checked"] = False
    result["real_customer_consent_verified"] = False
    result["owner_release_approval_recorded"] = False
    result["next_action"] = (
        "Approve isolated accounting staging resources separately, then "
        "run authenticated, read-only infrastructure acceptance before "
        "requesting any deployment approval."
    )
    assert result["status"] == "BLOCKED"
    assert result["production_release_authorized"] is False
    assert result["deployment_performed"] is False
    assert result["customer_data_allowed"] is False
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=str, default=None,
        help="Optional JSON report in a local build-artifact path (never cloud)",
    )
    options = parser.parse_args(argv)
    report = build_report(dict(os.environ))
    payload = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if options.output:
        dest = Path(options.output)
        if (
            len(options.output) > MAX_PATH
            or dest.is_absolute()
            or ".." in dest.parts
            or dest.suffix != ".json"
            or dest.is_symlink()
        ):
            parser.error("Only a relative local .json artifact path is allowed")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    # BLOCKED is an expected and safe result, not a failed code execution.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
