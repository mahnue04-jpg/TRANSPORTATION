"""Deferred platform startup work executed after the app begins serving traffic."""
from __future__ import annotations

import logging
import os
import sys
import time
import traceback
from typing import Any

logger = logging.getLogger("amicor.background_startup")

_deferred_status: dict[str, Any] = {
    "scheduled": False,
    "running": False,
    "complete": False,
    "error": None,
    "started_at": None,
    "completed_at": None,
    "duration_ms": None,
}


def deferred_startup_status() -> dict[str, Any]:
    return dict(_deferred_status)


def run_deferred_platform_startup(*, runtime_environment: str) -> None:
    """Initialize Health ISF runtime services without blocking Render boot."""
    global _deferred_status

    if _deferred_status.get("running") or _deferred_status.get("complete"):
        return

    _deferred_status.update(
        {
            "running": True,
            "started_at": time.time(),
            "error": None,
        }
    )
    started = time.perf_counter()
    logger.info("Deferred platform startup beginning…")

    try:
        health_isf_dir = os.path.join(os.path.dirname(__file__), "..", "modules", "health_isf")
        modules_dir = os.path.dirname(health_isf_dir)
        if modules_dir not in sys.path:
            sys.path.insert(0, modules_dir)

        logger.info("Deferred Health ISF module initialization…")
        from app.modules.health_isf import models as health_isf_models  # noqa: F401
        from app.modules.health_isf import ai_governance_engine as ai_governance_engine_module  # noqa: F401
        from app.modules.health_isf import approval_contract as approval_contract_module  # noqa: F401
        from app.modules.health_isf import correlation_engine as correlation_engine_module  # noqa: F401
        from app.modules.health_isf import governance_models as governance_models_module  # noqa: F401
        from app.modules.health_isf import governance_registry as governance_registry_module  # noqa: F401
        from app.modules.health_isf import operational_timeline as operational_timeline_module  # noqa: F401

        from app.db.session import Base, SessionLocal, engine  # type: ignore

        Base.metadata.create_all(bind=engine)
        logger.info("Deferred Health ISF tables verified.")

        try:
            from app.modules.health_isf.realtime import initialize_realtime  # type: ignore

            initialize_realtime()
            logger.info("Deferred real-time infrastructure initialized.")
        except Exception as rt_exc:
            logger.error("Deferred real-time infrastructure init failed: %s", rt_exc)

        from app.modules.health_isf import service as health_isf_service  # type: ignore
        from app.modules.health_isf.runtime_governor import initialize_runtime_governor  # type: ignore

        try:
            governor = initialize_runtime_governor(
                db_session_factory=SessionLocal,
                cleanup_interval_seconds=int(os.environ.get("RUNTIME_GOVERNOR_CLEANUP_INTERVAL_SECONDS", "60")),
                stale_after_seconds=int(os.environ.get("RUNTIME_GOVERNOR_STALE_AFTER_SECONDS", "300")),
            )
            logger.info(
                "Deferred runtime governor initialized | active_workflows=%s",
                governor.active_workflow_count,
            )
        except Exception as governor_exc:
            logger.error("Deferred runtime governor initialization failed: %s", governor_exc)

        db = SessionLocal()
        try:
            health_isf_service._get_or_create_default_org(db)  # type: ignore
            bootstrap_summary = health_isf_service.sync_operational_bootstrap(db)  # type: ignore
            provider_summary = (
                bootstrap_summary.get("summaries", [{}])[0].get("providers", {})
                if bootstrap_summary.get("summaries")
                else {}
            )
            driver_summary = (
                bootstrap_summary.get("summaries", [{}])[0].get("drivers", {})
                if bootstrap_summary.get("summaries")
                else {}
            )
            logger.info(
                "Deferred operational bootstrap complete: orgs=%s providers=%s drivers=%s",
                bootstrap_summary.get("organizations_synced"),
                provider_summary.get("total"),
                driver_summary.get("total"),
            )
            seed_sample_data = os.environ.get("AMICOR_SEED_SAMPLE_DATA", "").strip().lower() in {
                "1",
                "true",
                "yes",
            }
            if seed_sample_data or runtime_environment not in {"production", "prod"}:
                health_isf_service.init_sample_data(db)  # type: ignore
                logger.info("Deferred Health ISF sample seed complete.")
            else:
                logger.info("Deferred Health ISF sample seed skipped (production mode).")
        finally:
            db.close()

        _deferred_status.update(
            {
                "complete": True,
                "running": False,
                "completed_at": time.time(),
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        logger.info(
            "Deferred platform startup complete in %sms.",
            _deferred_status["duration_ms"],
        )
    except Exception as exc:
        _deferred_status.update(
            {
                "complete": False,
                "running": False,
                "error": f"{type(exc).__name__}: {exc}",
                "completed_at": time.time(),
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        logger.error("Deferred platform startup failed: %s", exc)
        traceback.print_exc()
