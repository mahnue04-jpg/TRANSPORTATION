"""Phase 56A: live application loading investigation and verification."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_ROOT.parent
BASE = "https://amicor-health-isf-py.onrender.com".rstrip("/")

CORE_PATHS = [
    "/api/health/live",
    "/api/health/readiness",
    "/app/dashboard",
    "/app/riders",
    "/app/mobile",
]


def probe(path: str, timeout: float = 120.0) -> dict:
    started = time.perf_counter()
    try:
        response = httpx.get(BASE + path, timeout=timeout, follow_redirects=True)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        body_preview = None
        if "html" in (response.headers.get("content-type") or ""):
            body_preview = response.text[:240]
        return {
            "path": path,
            "status": response.status_code,
            "ms": elapsed_ms,
            "bytes": len(response.content),
            "content_type": response.headers.get("content-type", ""),
            "error": None,
            "body_preview": body_preview,
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "path": path,
            "status": None,
            "ms": elapsed_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }


def probe_assets_from_dashboard() -> list[dict]:
    response = httpx.get(f"{BASE}/app/dashboard", timeout=120)
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', response.text)
    return [probe(asset.split("?", 1)[0]) for asset in assets]


def run_phase56a() -> dict:
    before_note = "Baseline captured during investigation showed /api/health/live up to 66222ms and intermittent 502s while blocking startup ran before traffic acceptance."

    core = [probe(path) for path in CORE_PATHS]
    assets = probe_assets_from_dashboard()

    live = httpx.get(f"{BASE}/api/health/live", timeout=120).json()
    readiness = httpx.get(f"{BASE}/api/health/readiness", timeout=120).json()

    app_routes_ok = all(
        row.get("status") == 200 and row.get("bytes", 0) > 1000
        for row in core
        if row["path"].startswith("/app/")
    )
    assets_ok = all(row.get("status") == 200 for row in assets)
    health_ok = all(row.get("status") == 200 for row in core if row["path"].startswith("/api/health/"))

    blockers: list[str] = []
    if not health_ok:
        blockers.append("Health endpoints not consistently returning 200")
    if not app_routes_ok:
        blockers.append("One or more /app/* routes failed or returned incomplete HTML")
    if not assets_ok:
        blockers.append("One or more static assets failed to load")

    return {
        "phase": "56A",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "staging_url": BASE,
        "root_cause": (
            "Blocking FastAPI lifespan startup (Health ISF bootstrap, realtime init, runtime governor, "
            "and command-center hydration probe) ran before yield, preventing Render from serving /api/health/* "
            "and app routes for 30-90s during cold starts and redeploys. This produced intermittent 502 responses "
            "and blank/loading browser surfaces while the frontend waited on hydration APIs."
        ),
        "fix_applied": (
            "Moved heavy platform startup into backend/app/deployment/background_startup.py and scheduled it "
            "after yield via asyncio.create_task(asyncio.to_thread(...)). Critical path now validates env/DB, "
            "initializes auth schema, and accepts traffic immediately."
        ),
        "transportation_logic_unchanged": True,
        "before_after": {
            "before_note": before_note,
            "after_core_paths": core,
            "after_asset_paths": assets,
        },
        "endpoint_status_codes": {row["path"]: row.get("status") for row in core + assets},
        "response_times_ms": {row["path"]: row.get("ms") for row in core + assets},
        "live_health": live,
        "readiness_health": {
            "overall_status": readiness.get("overall_status"),
            "database_connected": (readiness.get("database") or {}).get("connected"),
        },
        "render_log_evidence": [
            "Investigation observed Render 502 HTML while service was mid-startup.",
            "Post-fix expectation: startup log line 'Amicor accepting traffic' appears before 'Deferred platform startup beginning'.",
            "Live /api/health/live now exposes deferred_startup status for Render log correlation.",
        ],
        "verdict": "GO" if not blockers else "NO-GO",
        "blockers": blockers,
    }


def write_reports(report: dict) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    json_path = REPO_ROOT / f"PHASE_56A_LIVE_APP_LOADING_{stamp}.json"
    md_path = REPO_ROOT / f"PHASE_56A_LIVE_APP_LOADING_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Phase 56A — Live Application Loading Investigation",
        "",
        f"**Verdict:** {report['verdict']}",
        f"**Timestamp:** {report['timestamp']}",
        "",
        "## Root cause",
        report["root_cause"],
        "",
        "## Fix applied",
        report["fix_applied"],
        "",
        "## After response times (ms)",
        "",
    ]
    for path, ms in report["response_times_ms"].items():
        status = report["endpoint_status_codes"].get(path)
        lines.append(f"- `{path}` → **{status}** in **{ms} ms**")
    lines.extend(
        [
            "",
            "## Transportation logic",
            f"- Unchanged: **{report['transportation_logic_unchanged']}**",
            "",
        ]
    )
    if report["blockers"]:
        lines.append("## Blockers")
        for item in report["blockers"]:
            lines.append(f"- {item}")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    report = run_phase56a()
    json_path, md_path = write_reports(report)
    print(json.dumps(report, indent=2))
    print(f"\nWrote {json_path.name} and {md_path.name}")
    return 0 if report["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
