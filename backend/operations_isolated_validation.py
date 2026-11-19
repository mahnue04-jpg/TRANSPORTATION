"""Minimal Nova Operations validation ASGI service.

Only mounts owner-scoped Operations routes. No full app.main import, no
marketing schema changes, no default-user seeding, no background workers.
Requires explicit approval before any hosted deployment. Synthetic only.
"""
from __future__ import annotations

import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.nova.work_revenue.operations_owner_csv_api import router as operations_router

# Never import app.main here: that module initializes unrelated schemas at
# import and starts additional services through application lifespan.
app = FastAPI(
    title="Nova Operations isolated validation",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(operations_router, prefix="/api/nova/work")


def _enabled(key: str) -> bool:
    return os.getenv(key, "").strip().lower() == "true"


@app.get("/health", include_in_schema=False)
def health() -> JSONResponse:
    """No DB access, secret exposure, or proof of customer readiness."""
    return JSONResponse(
        content={
            "status": "isolated_validation",
            "synthetic_only": True,
            "customer_processing": False,
            "customer_delivery": False,
            "stripe_charges": False,
            "full_app_startup": False,
            "database_migration_performed": False,
        },
        headers={"Cache-Control": "no-store"},
    )


def _unsafe_configuration() -> bool:
    """Never permit a diagnostic instance to become a customer processor."""
    return (
        os.getenv("APP_ENV", "development").strip().lower() == "production"
        or os.getenv("AMICOR_ENVIRONMENT", "development").strip().lower() == "production"
        or _enabled("NOVA_STRIPE_LIVE_ENABLED")
        or _enabled("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED")
        or _enabled("NOVA_OPERATIONS_OWNER_CSV_ENABLED")
        or _enabled("NOVA_OPERATIONS_STARTER_BINDING_ENABLED")
        or _enabled("NOVA_OPERATIONS_DURABLE_CSV_ENABLED")
        or _enabled("NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED")
        or _enabled("NOVA_OPERATIONS_LEASE_WORKER_ENABLED")
    )



@app.on_event("startup")
def prevent_unsafe_validation_configuration() -> None:
    """Fail fast at startup with unsafe configuration."""
    if _unsafe_configuration():
        raise RuntimeError("Isolated Operations validation prohibits live or processing flags")


@app.middleware("http")
async def deny_customer_routes(request: Request, call_next):
    """No customer processing even if an environment flag changes after boot.

    Owner Operations routers are mounted to validate route registration, but
    they must never execute in the synthetic diagnostic process.
    """
    if request.url.path != "/health":
        return JSONResponse(
            status_code=503,
            content={"detail": "Operations isolated validation cannot process customer work"},
            headers={"Cache-Control": "no-store"},
        )
    if _unsafe_configuration():
        return JSONResponse(
            status_code=503,
            content={"detail": "Operations isolated validation configuration unsafe"},
            headers={"Cache-Control": "no-store"},
        )
    return await call_next(request)
