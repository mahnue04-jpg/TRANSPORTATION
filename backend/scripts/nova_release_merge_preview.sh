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
    "integration_ready": False,
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
        report["steps"].append({
            "pr": pr, "status": "CONFLICTS_REQUIRE_REVIEW",
            "conflicting_paths": sorted(unmerged)[:100],
        })
        cmd("git", "merge", "--abort", check=False)
        break
    cmd("git", "commit", "-m", f"CI ONLY: simulated integration of PR {pr}")
    report["steps"].append({"pr": pr, "status": "EPHEMERAL_MERGE_OK"})
else:
    report["integration_ready"] = True
report["next_action"] = (
    "Manually reconcile overlapping draft PR code and rerun combined functional tests "
    "before approval of isolated staging."
    if not report["integration_ready"] else
    "Run combined accounting, operations and revenue suites against this ephemeral tree."
)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
PY
