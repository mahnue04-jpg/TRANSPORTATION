"""Integration acceptance for Work & Revenue + Operations + Bookkeeping routes.

Run ONLY on the ephemeral merged PR 477 + PR 484 + PR 338 checkout.
Checks actual imported FastAPI route contracts and the server-side owner guards.
No real databases, providers, contacts, or customer records are used.
"""
from fastapi.routing import APIRoute

from app.core.nova.router import require_nova_access
from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
from app.core.nova.work_revenue.router import router as work_router
from app.core.nova.v3.router import router as v3_router


def _methods(router):
    result = {}
    for route in router.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                if method not in {"HEAD", "OPTIONS"}:
                    key = (method, route.path)
                    if key in result:
                        raise AssertionError(f"Duplicate route after PR merge: {key}")
                    result[key] = route
    return result


def _dependencies(route):
    return {dependency.call for dependency in route.dependant.dependencies}


def test_all_three_workflows_are_registered_in_combined_router():
    work = _methods(work_router)
    v3 = _methods(v3_router)
    required = (
        ("POST", "/api/nova/work/operations/durable/engagements/{engagement_id}/tasks/{task_id}/jobs"),
        ("GET", "/api/nova/work/operations/durable/jobs/{job_id}"),
        ("POST", "/api/nova/work/operations/durable/jobs/{job_id}/review"),
        ("GET", "/api/nova/work/operations/durable/jobs/{job_id}/download"),
        ("GET", "/api/nova/work/operations/durable/bookkeeping/review-queue"),
        ("GET", "/api/nova/work/operations/durable/bookkeeping/eligible-tasks"),
        ("POST", "/api/nova/work/operations/durable/bookkeeping/engagements/{engagement_id}/tasks/{task_id}/{work_type}/jobs"),
        ("GET", "/api/nova/work/operations/durable/bookkeeping/jobs/{job_id}"),
        ("POST", "/api/nova/work/operations/durable/bookkeeping/jobs/{job_id}/review"),
        ("GET", "/api/nova/work/operations/durable/bookkeeping/jobs/{job_id}/download"),
    )
    for item in required:
        assert item in work, f"Unregistered integrated endpoint {item}"
    assert ("POST", "/api/nova/v3/live/jobs/autopilot-cycle") in v3


def test_sensitive_finance_endpoints_keep_both_owner_and_nova_access_guards():
    work = _methods(work_router)
    for (method, path), route in work.items():
        if not path.startswith("/api/nova/work/operations/"):
            continue
        guards = _dependencies(route)
        assert require_work_revenue_owner in guards, f"Missing owner guard: {method} {path}"
        assert require_nova_access in guards, f"Missing Nova access guard: {method} {path}"


def test_customer_delivery_cannot_be_inferred_from_workpaper_routes():
    work = _methods(work_router)
    paths = {p for _, p in work}
    assert not any(
        path.startswith("/api/nova/work/operations/durable/bookkeeping/")
        and any(term in path for term in ("/send-to-client", "/auto-invoice", "/pay"))
        for path in paths
    )
