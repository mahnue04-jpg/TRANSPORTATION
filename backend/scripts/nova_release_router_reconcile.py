"""CI-only router reconciliation for PR 338 + Operations/Accounting.

Git textual merge can silently omit route registration when another draft
branch edits the tail of the Work & Revenue router. This tool ONLY adds the
known owner CSV router include in a temporary CI tree. No production writes.
"""
from pathlib import Path
import subprocess
import sys

ROUTER = Path("backend/app/core/nova/work_revenue/router.py")
API = Path("backend/app/core/nova/work_revenue/operations_owner_csv_api.py")
IMPORT = "from app.core.nova.work_revenue.operations_owner_csv_api import router as owner_csv_router"
INCLUDE = "router.include_router(owner_csv_router)"
V2 = "router.include_router(nova_work_v2_router)"


def run() -> None:
    if not API.is_file() or not ROUTER.is_file():
        raise ValueError("Accounting/Operations owner router missing")
    content = ROUTER.read_text(encoding="utf-8")
    if content.count(V2) != 1:
        raise ValueError("Unexpected Work & Revenue router registration shape")
    if content.count(IMPORT) != content.count(INCLUDE):
        raise ValueError("Partial or ambiguous owner router registration")
    if content.count(INCLUDE) == 1:
        print("Existing Operations owner router registration preserved.")
        return
    if content.count(INCLUDE) != 0:
        raise ValueError("Duplicate owner router registration")
    # Only append a known registration; never remove or rewire other routes.
    new_content = content.rstrip() + "\n\n" + IMPORT + "\n" + INCLUDE + "\n"
    ROUTER.write_text(new_content, encoding="utf-8")
    subprocess.run(["git", "add", str(ROUTER)], check=True)
    print("CI only: restored protected Operations/Accounting owner router registration.")


if __name__ == "__main__":
    try:
        run()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"NEEDS_MANUAL_ROUTE_REVIEW: {exc}", file=sys.stderr)
        raise SystemExit(1)
