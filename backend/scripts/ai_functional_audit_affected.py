"""Re-run only the two AI functional verification checks that previously failed."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = os.getenv("AMICOR_BROWSER_BASE", "https://amicor-health-isf-py.onrender.com")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
OUT = Path(__file__).resolve().parent.parent / "artifacts" / "ai_functional_audit_affected.json"


def main() -> int:
    login = httpx.post(
        f"{BASE}/api/auth/login",
        json={"email": "admin@amicor.local", "password": PASSWORD},
        timeout=120,
    )
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    session_id = "ai-affected-audit"

    checks: list[dict] = []

    intel = httpx.get(f"{BASE}/api/nova/intelligence", headers=headers, timeout=120)
    intel_ok = intel.status_code == 200
    intel_body = intel.json() if intel.headers.get("content-type", "").startswith("application/json") else {}
    checks.append(
        {
            "feature": "GET /api/nova/intelligence",
            "pass": intel_ok and isinstance(intel_body, dict) and "composite_score" in intel_body,
            "status": intel.status_code,
            "detail": "" if intel_ok else intel.text[:240],
            "evidence": {"composite_score": intel_body.get("composite_score") if isinstance(intel_body, dict) else None},
        }
    )

    for label, token in [
        ("invalid token", "bad"),
        ("malformed signature", "invalid.token.value"),
    ]:
        resp = httpx.post(
            f"{BASE}/api/assistant/confirm",
            headers=headers,
            json={
                "token": token,
                "intent_id": "x",
                "action_type": "preview",
                "session_id": session_id,
                "intent_hash": "x",
                "preview_payload_hash": "x",
                "dependency_graph_hash": "x",
                "safety_classification_hash": "x",
                "supervision_classification": {},
                "nonce": "x",
            },
            timeout=120,
        )
        checks.append(
            {
                "feature": f"POST /api/assistant/confirm ({label})",
                "pass": resp.status_code in {401, 403, 422},
                "status": resp.status_code,
                "detail": resp.json().get("detail", resp.text[:240]) if resp.content else "",
            }
        )

    all_ok = all(c["pass"] for c in checks)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "target": BASE,
        "checks": checks,
        "all_pass": all_ok,
        "verdict": "PASS" if all_ok else "FAIL",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
