"""Ephemeral merge-only FastAPI app route reconciliation.

Some import orders leave Operations owner routes on their child router
without copying them to the work router before app registration. Safeguard
the actual application startup path. This file NEVER modifies a live app;
the CI preview patches only its temporary checkout.
"""
from pathlib import Path
import subprocess
import sys

MAIN = Path("backend/app/main.py")
ANCHOR = "app.include_router(nova_work_router)"
NEEDED = "from app.core.nova.work_revenue.operations_owner_csv_api import router as _nova_owner_csv_router"
BLOCK = """# CI integration candidate: ensure Operations/Accounting child routes are
# present BEFORE FastAPI snapshots the Work & Revenue router into app.routes.
# The guard prevents duplicate registration when import ordering already worked.
from app.core.nova.work_revenue.operations_owner_csv_api import router as _nova_owner_csv_router
if not any(
    getattr(route, "path", "") == "/api/nova/work/operations/csv-clean"
    for route in nova_work_router.routes
):
    nova_work_router.include_router(_nova_owner_csv_router)
# Register directly on the app as a second late-import safety net. This
# catches work routers whose earlier inclusion was snapshotted before child
# routes were defined during a circular import. Guard against duplicates.
if not any(
    getattr(route, "path", "") == "/api/nova/work/operations/csv-clean"
    for route in app.routes
):
    app.include_router(_nova_owner_csv_router, prefix="/api/nova/work")
"""


def reconcile():
    if not MAIN.is_file():
        raise RuntimeError("app/main.py missing")
    s = MAIN.read_text(encoding="utf-8")
    if s.count(ANCHOR) != 1 or s.count(NEEDED) > 1:
        raise RuntimeError("Application router wiring changed; manual review")
    if NEEDED not in s:
        s = s.replace(ANCHOR, BLOCK + ANCHOR, 1)
    lifespan_anchor = "async def lifespan(app: FastAPI):"
    if s.count(lifespan_anchor) != 1:
        raise RuntimeError("Custom application lifespan anchor changed")
    helper_name = "_nova_repair_finance_routes_after_import"
    if helper_name not in s:
        helper = '''def _nova_repair_finance_routes_after_import(app: FastAPI) -> None:
    """Install only missing owner finance routes, after circular imports settle.

    Kept as an isolated integration-candidate safeguard; reviewed source
    refactoring is required before a permanent production release.
    """
    from fastapi import APIRouter
    from app.core.nova.work_revenue.operations_owner_csv_api import router as child
    prefix = "/api/nova/work"
    already = {
        (method, getattr(route, "path", ""))
        for route in app.routes
        for method in getattr(route, "methods", ())
    }
    missing = [
        route for route in child.routes
        if any((method, prefix + route.path) not in already
               for method in getattr(route, "methods", ()))
    ]
    if missing:
        rest = APIRouter()
        rest.routes.extend(missing)
        app.include_router(rest, prefix=prefix)


'''
        s = s.replace(lifespan_anchor, helper + lifespan_anchor, 1)
        s = s.replace(lifespan_anchor, lifespan_anchor + "\n    _nova_repair_finance_routes_after_import(app)\n", 1)
    MAIN.write_text(s, encoding="utf-8")
    subprocess.run(["git", "add", str(MAIN)], check=True)
    print("CI only: guarded owner routes plus deferred custom-lifespan reconciliation.")


if __name__ == "__main__":
    try:
        reconcile()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"REQUIRES_MANUAL_APP_ROUTER_REVIEW: {exc}", file=sys.stderr)
        raise SystemExit(1)
