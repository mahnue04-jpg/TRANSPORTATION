"""Full pilot-operation browser audit with JSON + markdown report."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))

import browser_pilot_workflow_verification as pilot  # noqa: E402

REPORT_JSON = BACKEND_ROOT / "artifacts" / "pilot_operation_audit.json"
REPORT_MD = BACKEND_ROOT / "artifacts" / "PILOT_OPERATION_AUDIT_REPORT.md"


def build_markdown(proof: dict) -> str:
    steps = proof.get("steps") or []
    verdict = proof.get("verdict") or "FAIL"
    lines = [
        "# Pilot Operation Audit Report",
        "",
        f"**Generated:** {proof.get('finished_at') or datetime.now(timezone.utc).isoformat()}",
        f"**Target:** {proof.get('base')}",
        f"**Verdict:** {verdict}",
        "",
        "## Workflow steps",
        "",
    ]
    for step in steps:
        lines.append(f"- {step}")
    lines.extend([
        "",
        "## Ride",
        "",
        f"- Ride ID: `{proof.get('ride_id', 'n/a')}`",
        f"- Passenger: `{proof.get('passenger', 'n/a')}`",
        "",
        "## Reset",
        "",
        "```json",
        json.dumps(proof.get("reset") or {}, indent=2),
        "```",
        "",
        "## AI checks",
        "",
        "```json",
        json.dumps(
            {
                "ai_intelligence": proof.get("ai_intelligence"),
                "ai_dispatch": proof.get("ai_dispatch"),
            },
            indent=2,
        ),
        "```",
        "",
        "## Screenshots",
        "",
    ])
    for shot in proof.get("screenshots") or []:
        if isinstance(shot, dict):
            lines.append(f"- {shot.get('name')}: `{shot.get('path')}`")
        else:
            lines.append(f"- `{shot}`")
    lines.extend([
        "",
        "## Production readiness",
        "",
        "Ready for pilot operations only when verdict is **PASS** and all cross-app panels show the same live ride.",
        "",
    ])
    if verdict != "PASS":
        lines.append("**Status: NOT READY** — fix failing steps and re-run audit.")
    else:
        lines.append("**Status: PILOT READY** — real ride lifecycle verified in browser.")
    return "\n".join(lines)


def main() -> int:
    code = pilot.main()
    if REPORT_JSON.exists():
        proof = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    else:
        proof = {"verdict": "FAIL", "steps": ["audit script did not produce JSON"]}
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(build_markdown(proof), encoding="utf-8")
    print(f"[REPORT] {REPORT_MD}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
