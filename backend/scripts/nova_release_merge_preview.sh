#!/usr/bin/env bash
# CI-only integration preview. No pushes, deployments, secrets or production DB.
set -euo pipefail
OUT="${1:-/tmp/nova-release-merge-report.json}"
python3 - "$OUT" <<'PY'
import json, subprocess, sys
from pathlib import Path

output = Path(sys.argv[1])
def cmd(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)
report = {
    "mode": "EPHEMERAL_CI_MERGE_PREVIEW",
    "production_merged": False,
    "github_prs_merged": False,
    "render_deployed": False,
    "release_approved": False,
    "branches": ["refs/pull/477/head", "refs/pull/484/head", "refs/pull/338/head"],
    "merge_conflict_free": False,
    "integration_tests_passed": False,
    "human_merge_resolution_reviewed": False,
    "steps": [],
}
cmd("git", "config", "user.name", "Nova CI integration preview")
cmd("git", "config", "user.email", "nova-ci@example.invalid")
# Pull refs only: no trust in arbitrary external head repositories.
for pr in ("477", "484", "338"):
    cmd("git", "fetch", "--no-tags", "origin", f"refs/pull/{pr}/head:refs/remotes/origin/release-preview-{pr}")
cmd("git", "checkout", "-B", "nova-release-preview-ephemeral", "refs/remotes/origin/release-preview-477")
for pr in ("484", "338"):
    target = f"refs/remotes/origin/release-preview-{pr}"
    merged = cmd("git", "merge", "--no-ff", "--no-commit", target, check=False)
    if merged.returncode != 0:
        unmerged = cmd("git", "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
        if pr == "338" and unmerged == ["backend/static/nova-work/index.html"]:
            reconciled = cmd(
                "python3", "backend/scripts/nova_release_dashboard_reconcile.py",
                check=False,
            )
            if reconciled.returncode == 0:
                cmd("git", "commit", "-m", "CI ONLY: reconcile Revenue, Operations and Accounting dashboard")
                report["steps"].append({
                    "pr": pr, "status": "DASHBOARD_CONFLICT_RECONCILED_CI_ONLY",
                    "conflicting_paths": unmerged,
                    "merge_resolution_review_required": True,
                })
                continue
        report["steps"].append({
            "pr": pr, "status": "CONFLICTS_REQUIRE_REVIEW",
            "conflicting_paths": sorted(unmerged)[:100],
        })
        cmd("git", "merge", "--abort", check=False)
        break
    # Git may report an already-contained change without creating MERGE_HEAD.
    # Do not fail or manufacture a merge commit for that case.
    pending = cmd("git", "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    if pending.returncode == 0:
        cmd("git", "commit", "-m", f"CI ONLY: simulated integration of PR {pr}")
        outcome = "EPHEMERAL_MERGE_OK"
    else:
        outcome = "ALREADY_CONTAINED"
    report["steps"].append({"pr": pr, "status": outcome})
else:
    # Textual merge success alone is insufficient: PR #338 can silently
    # omit a registered Operations/Accounting subrouter in the shared router.
    checked = cmd("python3", "backend/scripts/nova_release_router_reconcile.py", check=False)
    if checked.returncode == 0:
        changed = cmd("git", "diff", "--cached", "--quiet", check=False)
        if changed.returncode == 1:
            cmd("git", "commit", "-m", "CI ONLY: restore Operations owner API routes")
            report["steps"].append({
                "pr": "cross-pr-route", "status": "ROUTER_REGISTRATION_RESTORED_CI_ONLY",
                "human_review_required": True,
            })
        else:
            report["steps"].append({"pr": "cross-pr-route", "status": "ROUTER_REGISTRATION_PRESENT"})
        app_routes = cmd("python3", "backend/scripts/nova_release_main_router_reconcile.py", check=False)
        if app_routes.returncode == 0:
            changed_app = cmd("git", "diff", "--cached", "--quiet", check=False)
            if changed_app.returncode == 1:
                cmd("git", "commit", "-m", "CI ONLY: register guarded owner finance routes before app startup")
                report["steps"].append({
                    "pr": "cross-pr-app", "status": "APP_ROUTE_SNAPSHOT_SAFEGUARD_CI_ONLY",
                    "human_review_required": True,
                })
            report["merge_conflict_free"] = True
        else:
            report["steps"].append({"pr": "cross-pr-app", "status": "APP_ROUTE_RECONCILIATION_BLOCKED"})
    else:
        report["steps"].append({"pr": "cross-pr-route", "status": "ROUTER_RECONCILIATION_BLOCKED"})
report["next_action"] = (
    "Manually reconcile overlapping draft PR code and rerun combined functional tests "
    "before approval of isolated staging."
    if not report["merge_conflict_free"] else
    "Merge preview has no textual conflicts. Combined functional tests are still required."
)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
PY
