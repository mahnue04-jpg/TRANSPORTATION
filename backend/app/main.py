from dotenv import load_dotenv
load_dotenv()

import asyncio
import base64
import hashlib
import hmac
import json
import os
import logging
import importlib
import platform
import secrets
import subprocess
import threading
import time
from datetime import datetime, timezone
from io import BytesIO
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, cast
from urllib.parse import urlparse
from zipfile import BadZipFile

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse, Response
from pydantic import BaseModel, Field

from app.deployment.release_version import resolve_app_version

# Guard against Python 3.13 Windows WMI stalls during platform.machine() at import time.
if os.name == "nt" and os.getenv("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1") == "1":
    _arch_hint = (os.getenv("PROCESSOR_ARCHITEW6432") or os.getenv("PROCESSOR_ARCHITECTURE") or "").upper()
    _arch_map = {
        "AMD64": "AMD64",
        "X86": "x86",
        "ARM64": "ARM64",
        "ARM": "ARM",
    }

    def _amicor_machine() -> str:
        return _arch_map.get(_arch_hint, "AMD64")

    platform.machine = _amicor_machine  # type: ignore[assignment]

from sqlalchemy.orm import Session

from app.database import clear_user_memory, get_chat_history, get_memory_summary, get_preferences, init_db  # type: ignore
from app.models import ChatRequest, ResetRequest   # type: ignore
from app.router import route_message              # type: ignore
from app import startup as app_startup            # type: ignore
from app import image_ocr                         # type: ignore

from app.middleware import SecurityHeadersMiddleware, RequestTracingMiddleware, log_upload  # type: ignore
from app.core.error_boundary import ErrorBoundaryMiddleware  # type: ignore
from app.core.runtime_config import validate_runtime_config  # type: ignore
from app import auth as auth_module               # type: ignore
from app.auth import UserContext, get_current_user_context, ROLE_ADMIN, ROLE_ANALYTICS_READONLY, ROLE_DISPATCHER, ROLE_STAFF, ROLE_SUPER_ADMIN_SUPPORT  # type: ignore
from app import observability                     # type: ignore
from app.tenant_auth_middleware import TenantAuthValidationMiddleware  # type: ignore
from app import ecosystem as ecosystem_module     # type: ignore
from app import voice as voice_module             # type: ignore
from app import responses as responses_module     # type: ignore
from app import validation as validation_module   # type: ignore
from app import logging_utils                     # type: ignore
from app.core.nova import router as nova_router, actions_router as nova_actions_router  # type: ignore
from app.core.nova.command_center_router import router as command_center_router  # type: ignore
from app.core.nova.operational_health_router import router as health_router  # type: ignore
from app.core.nova.operational_hydration_router import router as ops_hydration_router  # type: ignore
from app.core.nova.compliance_router import router as compliance_router, orchestration_router, federation_router, replay_router, predictive_router, governance_router  # type: ignore
from app.core.nova.assistant_execution_router import router as assistant_execution_router  # type: ignore
from app.core.nova.assistant_execution_service import execute_verified_intent, log_operational_event  # type: ignore
from app.core.nova.assistant_contract import (  # type: ignore
    normalize_assistant_preview_payload,
    normalize_supervision_classification,
)
from app.db.models import AssistantGovernanceLedger, AssistantPreviewRecord
from app.db.session import SessionLocal, get_db  # type: ignore
from app.runtime_contract import (
    CANONICAL_BACKEND_URL,
    CANONICAL_FRONTEND_URL,
    CANONICAL_WEBSOCKET_URL,
    FRONTEND_BUILD_VERSION,
    HYDRATION_VERSION,
    RUNTIME_CONTRACT,
    RUNTIME_ENVIRONMENT,
    build_runtime_contract,
    inject_runtime_contract,
)
from app.modules.health_isf.runtime_governor import (  # type: ignore
    initialize_runtime_governor,
    shutdown_runtime_governor,
)

# ── Logging ───────────────────────────────────────────────────────────────────
_log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO"), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("amicor.main")


def _expected_backend_port() -> int:
    try:
        parsed = urlparse(CANONICAL_BACKEND_URL)
        if parsed.port:
            return int(parsed.port)
    except Exception:
        pass
    return int(os.environ.get("PORT", "8011"))


def _listener_ownership_snapshot(expected_port: int) -> dict[str, Any]:
    current_pid = os.getpid()
    snapshot: dict[str, Any] = {
        "expected_port": int(expected_port),
        "current_pid": int(current_pid),
        "listener_found": False,
        "listener_owner_pid": None,
        "ownership_ok": False,
        "stale_worker_detected": False,
        "raw_match": "",
    }
    try:
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        needle = f"127.0.0.1:{expected_port}"
        for line in output.splitlines():
            if needle not in line or "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if not parts:
                continue
            owner_pid = None
            try:
                owner_pid = int(parts[-1])
            except Exception:
                owner_pid = None
            snapshot.update(
                {
                    "listener_found": owner_pid is not None,
                    "listener_owner_pid": owner_pid,
                    "ownership_ok": owner_pid == current_pid,
                    "stale_worker_detected": owner_pid not in {None, current_pid},
                    "raw_match": line.strip(),
                }
            )
            break
    except Exception as exc:
        snapshot["probe_error"] = type(exc).__name__
    return snapshot


async def _bootstrap_health_probe(organization_id: str) -> dict[str, Any]:
    probe_started = time.perf_counter()
    result: dict[str, Any] = {
        "organization_id": organization_id,
        "health_check_status": "unknown",
        "hydration_status": "unknown",
        "hydration_ms": 0,
        "probe_ms": 0,
    }
    try:
        from app.core.nova.health_check_engine import health_check_engine, HealthCheckType
        from app.core.nova.command_center_hydration import command_center_hydration

        health_result = await health_check_engine.run_health_check(
            organization_id,
            HealthCheckType.COMMAND_CENTER_HYDRATION,
        )
        result["health_check_status"] = health_result.status.value

        hydration_started = time.perf_counter()
        snapshot = command_center_hydration.build_full_hydration(organization_id)
        hydration_ms = int((time.perf_counter() - hydration_started) * 1000)
        missing = list(snapshot.get("missing") or []) if isinstance(snapshot, dict) else []
        result["hydration_ms"] = hydration_ms
        result["hydration_missing_count"] = len(missing)
        result["hydration_status"] = "degraded" if missing else "healthy"
    except Exception as exc:
        result["health_check_status"] = "error"
        result["hydration_status"] = "error"
        result["probe_error"] = type(exc).__name__
    result["probe_ms"] = int((time.perf_counter() - probe_started) * 1000)
    return result

# ── Upload constraints ────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
OPENAI_TIMEOUT_SECONDS = 30.0
ALLOWED_UPLOAD_TYPES = frozenset({
    "text/plain", "text/markdown", "text/csv",
    "application/json", "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png", "image/jpeg", "image/webp",
})


# ── CORS ─────────────────────────────────────────────────────────────────────
def _allowed_origins() -> list: # type: ignore
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    if raw.strip():
        return [o.strip() for o in raw.split(",") if o.strip()] # type: ignore
    # Secure-by-default local dev origins; override via ALLOWED_ORIGINS in deployment.
    return [
        "http://127.0.0.1:8011",
        "http://localhost:8011",
    ] # type: ignore


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────────────────────
    logger.info("Amicor starting up…")
    startup_started_at = time.perf_counter()
    process_lineage = {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "thread": threading.get_ident(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    expected_port = _expected_backend_port()
    logger.info(
        "Runtime topology | frontend=%s backend=%s websocket=%s env=%s build=%s hydration=%s",
        CANONICAL_FRONTEND_URL,
        CANONICAL_BACKEND_URL,
        CANONICAL_WEBSOCKET_URL,
        RUNTIME_ENVIRONMENT,
        FRONTEND_BUILD_VERSION,
        HYDRATION_VERSION,
    )
    app_startup.register_shutdown_handlers()

    report = app_startup.run_startup_validation() # type: ignore
    if report["environment"]["missing_required"]:
        logger.critical(
            "Missing required env vars: %s — functionality will be degraded.",
            report["environment"]["missing_required"], # type: ignore
        )

    db_ok = app_startup.startup_recovery(max_retries=3, delay_s=1.0)
    if db_ok:
        try:
            init_db()
            logger.info("Database initialised.")
        except Exception as exc:
            logger.error("init_db() failed: %s", exc)
    else:
        logger.critical("Database unavailable after retries — chat persistence disabled.")

    # ── Platform DB (SQLAlchemy) ──────────────────────────────────────────
    try:
        from app.db.session import init_platform_db  # type: ignore
        init_platform_db()
        logger.info("Platform database tables ready.")
        try:
            auth_module.ensure_auth_schema()
            seeded = auth_module.seed_default_users()
            if seeded:
                logger.info("Seeded default auth users: %s", ", ".join(item["email"] for item in seeded))
            else:
                logger.info("Default auth users already present.")
        except Exception as auth_exc:
            logger.error("Auth schema/seed initialization failed: %s", auth_exc)

        try:
            from app.modules.health_isf.models import ensure_health_isf_schema  # type: ignore
            ensure_health_isf_schema()
            logger.info("Health ISF schema verified.")
            from app.modules.health_isf.models import ensure_driver_mobile_login_schema  # type: ignore
            ensure_driver_mobile_login_schema()
            logger.info("Driver mobile login schema verified.")
        except Exception as health_schema_exc:
            logger.error("Health ISF schema initialization failed: %s", health_schema_exc)
    except Exception as exc:
        logger.error("Platform DB init failed: %s", exc)

    from app.deployment.release_version import resolve_app_version

    logger.info(
        "Amicor accepting traffic. version=%s deferred_init=scheduled",
        resolve_app_version(),
    )

    async def _deferred_startup_runner() -> None:
        from app.deployment.background_startup import run_deferred_platform_startup

        await asyncio.to_thread(run_deferred_platform_startup, runtime_environment=RUNTIME_ENVIRONMENT)
        try:
            from app.monitoring.runtime_logger import record_supervision_event

            listener_snapshot = _listener_ownership_snapshot(expected_port)
            bootstrap_probe = await _bootstrap_health_probe(
                os.environ.get("DEFAULT_ORGANIZATION_ID", "global"),
            )
            _cfg_snapshot: dict = {}
            try:
                _cfg_snapshot = validate_runtime_config()
            except Exception:
                pass
            record_supervision_event(
                subsystem="runtime",
                event="startup",
                details={
                    "version": str(report.get("version", "dev")),
                    "environment": RUNTIME_ENVIRONMENT,
                    "runtime_config_status": _cfg_snapshot.get("validation_status", "unknown"),
                    "missing_required": _cfg_snapshot.get("missing_required", []),
                    "missing_optional": _cfg_snapshot.get("missing_optional", []),
                    "process_lineage": process_lineage,
                    "restart_attribution": {
                        "reason": os.environ.get("AMICOR_RUNTIME_RECOVERY_REASON", "unspecified"),
                        "session": os.environ.get("AMICOR_RUNTIME_RECOVERY_SESSION", "none"),
                    },
                    "listener_ownership": listener_snapshot,
                    "bootstrap_probe": bootstrap_probe,
                    "startup_ms": int((time.perf_counter() - startup_started_at) * 1000),
                    "deferred_startup": True,
                },
            )
        except Exception:
            pass

    from app.deployment.background_startup import deferred_startup_status

    deferred_startup_status()["scheduled"] = True
    deferred_task = asyncio.create_task(_deferred_startup_runner())

    yield  # ── APPLICATION RUNNING ──────────────────────────────────────────

    deferred_task.cancel()
    try:
        await deferred_task
    except asyncio.CancelledError:
        pass
    except Exception as deferred_exc:
        logger.error("Deferred startup task shutdown error: %s", deferred_exc)

    # ── SHUTDOWN ─────────────────────────────────────────────────────────────
    try:
        from app.monitoring.runtime_logger import record_supervision_event
        from app.monitoring.runtime_metrics import get_runtime_metrics
        from app.monitoring.system_metrics import get_active_request_count

        _rt = get_runtime_metrics()
        record_supervision_event(
            subsystem="runtime",
            event="shutdown_initiated",
            details={
                "uptime_seconds": _rt.get("uptime_seconds", 0),
                "active_requests": get_active_request_count(),
                "environment": RUNTIME_ENVIRONMENT,
            },
        )
    except Exception:
        pass

    try:
        shutdown_runtime_governor()
    except Exception as governor_shutdown_exc:
        logger.error("Runtime governor shutdown failed: %s", governor_shutdown_exc)

    try:
        from app.monitoring.runtime_logger import record_supervision_event
        from app.monitoring.runtime_metrics import get_runtime_metrics

        _rt = get_runtime_metrics()
        record_supervision_event(
            subsystem="runtime",
            event="shutdown_completed",
            details={
                "uptime_seconds": _rt.get("uptime_seconds", 0),
                "environment": RUNTIME_ENVIRONMENT,
            },
        )
    except Exception:
        pass

    logger.info("Amicor shutting down gracefully…")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Amicor AI Assistant",
    description="Production AI assistant backend.",
    version=resolve_app_version(),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(), # type: ignore
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestTracingMiddleware)
app.add_middleware(TenantAuthValidationMiddleware)
# Phase 7: ErrorBoundaryMiddleware added last → outermost layer in Starlette's
# reversed-stack build order; catches all unhandled exceptions and returns safe JSON.
app.add_middleware(ErrorBoundaryMiddleware)


@app.middleware("http")
async def disable_dev_static_cache(
    request: Request,
    call_next: Any,
) -> Response:
    """Disable browser caching for static assets during local development."""
    response = cast(Response, await call_next(request))
    if RUNTIME_ENVIRONMENT.lower() == "development" and request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ── Auth router ───────────────────────────────────────────────────────────────
app.include_router(auth_module.router)
app.include_router(ecosystem_module.router)
app.include_router(voice_module.router)
app.include_router(nova_router)
app.include_router(nova_actions_router)
app.include_router(command_center_router)
app.include_router(health_router)
app.include_router(ops_hydration_router)
app.include_router(compliance_router)
app.include_router(orchestration_router)
app.include_router(federation_router)
app.include_router(replay_router)
app.include_router(predictive_router)
app.include_router(governance_router)
app.include_router(assistant_execution_router)

# ── Health ISF module router ───────────────────────────────────────────────────
try:
    # Add app/modules to path temporarily to make imports work
    import sys
    health_isf_dir = os.path.join(os.path.dirname(__file__), "modules", "health_isf")
    modules_dir = os.path.dirname(health_isf_dir)
    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)
    
    from app.modules.health_isf.routes import (
        router as health_isf_router,
        public_router as health_isf_public_router,
        websocket_router as health_isf_websocket_router,
    )  # type: ignore
    from app.modules.health_isf.ai_operations_routes import router as health_isf_ai_router  # type: ignore
    app.include_router(health_isf_public_router)
    app.include_router(health_isf_router)
    app.include_router(health_isf_websocket_router)
    app.include_router(health_isf_ai_router)
    logger.info("Health ISF routes registered")
except Exception as exc:
    logger.error("Failed to register Health ISF routes: %s", exc)
    import traceback
    traceback.print_exc()

# ── Platform Ops (business operations — separate from frozen ride engine) ─────
try:
    from app.modules.platform_ops.routes import router as platform_ops_router  # type: ignore

    app.include_router(platform_ops_router)
    logger.info("Platform Ops routes registered")
except Exception as exc:
    logger.error("Failed to register Platform Ops routes: %s", exc)
    import traceback
    traceback.print_exc()


# ── Health monitoring endpoints ───────────────────────────────────────────────

@app.get("/api/health/live", tags=["health"])
def health_live():
    """Liveness probe — confirms the process is running."""
    from app.deployment.background_startup import deferred_startup_status

    return {
        "status": "ok",
        "version": resolve_app_version(),
        "environment": RUNTIME_ENVIRONMENT,
        "frontend_build_version": FRONTEND_BUILD_VERSION,
        "hydration_version": HYDRATION_VERSION,
        "deploy_commit": os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT"),
        "deploy_branch": os.environ.get("RENDER_GIT_BRANCH") or os.environ.get("GIT_BRANCH"),
        "deferred_startup": deferred_startup_status(),
    }


@app.get("/api/runtime/topology", tags=["health"])
def runtime_topology(request: Request) -> dict[str, str]:
    """Expose canonical runtime topology for frontend diagnostics and verification."""
    topology = dict(build_runtime_contract(request=request))
    topology["app_version"] = resolve_app_version()
    topology["deploy_commit"] = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT") or ""
    topology["deploy_branch"] = os.environ.get("RENDER_GIT_BRANCH") or os.environ.get("GIT_BRANCH") or ""
    return topology


@app.get("/api/enterprise/dashboard")
def enterprise_dashboard(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    from app.modules.health_isf.routes import _build_enterprise_dashboard_payload  # type: ignore
    from app.modules.health_isf.security import enforce_tenant_scope  # type: ignore

    if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER, ROLE_STAFF, ROLE_ANALYTICS_READONLY}:
        raise HTTPException(status_code=403, detail="Enterprise dashboard access required")

    effective_org_id = enforce_tenant_scope(user, organization_id)
    return _build_enterprise_dashboard_payload(db, effective_org_id)


@app.get("/api/health/readiness", tags=["health"])
def health_readiness():
    """
    Readiness probe with structured environment and config checks.
    Returns 200 only when overall_status is ready (production env + config + DB).
    Returns 503 with blocked_reasons when deployment blockers are present.
    """
    from app.deployment.readiness import DeploymentReadinessChecker
    from fastapi.responses import JSONResponse

    report = DeploymentReadinessChecker.build_readiness_report()
    status_code = 200 if report["overall_status"] == "ready" else 503
    return JSONResponse(content=report, status_code=status_code)


@app.get("/api/health/operational", tags=["health"])
def health_operational():
    """
    Operational health snapshot: DB connectivity, WebSocket status, and runtime governor telemetry.
    Suitable for monitoring dashboards and uptime checks.
    """
    from app.deployment.readiness import build_health_monitoring_payload
    from app.db.session import check_db_connection
    from app.modules.health_isf.runtime_governor import get_runtime_governor
    from datetime import datetime, timezone

    logger.info({"event": "health_runtime_requested"})

    try:
        from app.modules.health_isf.realtime import get_broadcaster
        ws_stats = get_broadcaster().get_websocket_health_stats() # type: ignore
    except Exception:
        ws_stats = {}

    db_ok = check_db_connection()
    payload = build_health_monitoring_payload(db_ok=db_ok, ws_stats=ws_stats) # type: ignore

    try:
        from app.monitoring.runtime_logger import record_supervision_event
        if not db_ok:
            record_supervision_event(
                subsystem="health",
                event="operational_probe_failed",
                details={
                    "db_ok": False,
                    "db_status": payload.get("db", {}).get("status") if isinstance(payload, dict) else None,
                },
            )
    except Exception:
        pass

    # --- Runtime Governor Telemetry ---
    try:
        governor = get_runtime_governor()
        snapshot = governor.get_health_snapshot() or {}
        telemetry = {
            "status": snapshot.get("status", "initializing"),
            "runtime_governor_status": snapshot.get("status", "initializing"),
            "active_workflows": int(snapshot.get("active_workflows", 0) or 0),
            "completed_workflows": int(snapshot.get("completed_workflows", 0) or 0),
            "orphan_workflows_detected": int(snapshot.get("orphan_workflows_detected", snapshot.get("orphan_workflows", 0)) or 0),
            "stale_events_rejected": int(snapshot.get("stale_events_rejected", 0) or 0),
            "replay_events_rejected": int(snapshot.get("replay_events_rejected", 0) or 0),
            "duplicate_events_rejected": int(snapshot.get("duplicate_events_rejected", 0) or 0),
            "lifecycle_transition_rejects": int(snapshot.get("lifecycle_transition_rejects", 0) or 0),
            "websocket_connects": int(snapshot.get("websocket_connects", 0) or 0),
            "websocket_disconnects": int(snapshot.get("websocket_disconnects", 0) or 0),
            "websocket_reconnects": int(snapshot.get("websocket_reconnects", 0) or 0),
            "governor_cleanup_cycles": int(snapshot.get("cleanup_cycles", 0) or 0),
            "crash_recovery_runs": int(snapshot.get("crash_recovery_runs", 0) or 0),
            "latest_cleanup_timestamp": snapshot.get("latest_cleanup_timestamp"),
            "latest_crash_recovery_timestamp": snapshot.get("latest_crash_recovery_timestamp"),
        }
        logger.info({"event": "telemetry_integrity_validated"})
        logger.info({"event": "telemetry_snapshot_generated", "telemetry": telemetry})
    except Exception as exc:
        telemetry = {
            "status": "degraded",
            "runtime_governor_status": "degraded",
            "active_workflows": 0,
            "completed_workflows": 0,
            "orphan_workflows_detected": 0,
            "stale_events_rejected": 0,
            "replay_events_rejected": 0,
            "duplicate_events_rejected": 0,
            "lifecycle_transition_rejects": 0,
            "websocket_connects": 0,
            "websocket_disconnects": 0,
            "websocket_reconnects": 0,
            "governor_cleanup_cycles": 0,
            "crash_recovery_runs": 0,
            "latest_cleanup_timestamp": None,
            "latest_crash_recovery_timestamp": None,
        }
        logger.warning({"event": "telemetry_snapshot_failed", "error_type": type(exc).__name__})

    payload["runtime_governor_telemetry"] = telemetry
    try:
        chain = _verify_assistant_ledger_tail()
        assistant_telemetry = _assistant_metric_snapshot()
        assistant_telemetry["audit_chain_verified"] = bool(chain.get("verified"))
        assistant_telemetry["audit_chain_verified_events"] = int(chain.get("verified_events", 0) or 0)
        assistant_telemetry["audit_chain_last_hash"] = str(chain.get("last_event_hash") or "GENESIS")
    except Exception:
        assistant_telemetry = _assistant_metric_snapshot()
        assistant_telemetry["audit_chain_verified"] = False
        assistant_telemetry["audit_chain_verified_events"] = 0
        assistant_telemetry["audit_chain_last_hash"] = "UNKNOWN"

    payload["assistant_security_telemetry"] = assistant_telemetry
    return payload


@app.get("/api/system/health", tags=["health"])
def system_health() -> dict[str, Any]:
    """Read-only runtime-safe operational snapshot for backend monitoring."""
    from app.monitoring.health_snapshot import build_system_health_snapshot
    from app.monitoring.runtime_logger import record_supervision_event

    record_supervision_event(
        subsystem="health",
        event="health_snapshot_accessed",
        details={"endpoint": "/api/system/health"},
    )

    return build_system_health_snapshot()


@app.get("/api/system/supervision", tags=["health"])
def system_supervision() -> dict[str, Any]:
    """Read-only supervision snapshot for controlled runtime visibility."""
    from app.monitoring.supervision_snapshot import build_supervision_snapshot
    from app.monitoring.runtime_logger import record_supervision_event

    record_supervision_event(
        subsystem="supervision",
        event="supervision_endpoint_accessed",
        details={"endpoint": "/api/system/supervision"},
    )

    return build_supervision_snapshot()


class AssistantBridgeRequest(BaseModel):
    """Phase 13 request contract for preview-only assistant interactions."""

    intent: str = Field(default="preview")
    prompt: str = Field(default="")
    role: str = Field(default="admin")
    scope: str = Field(default="assistant-workspace")
    session_id: str = Field(default="")
    context: dict[str, Any] = Field(default_factory=dict)


class AssistantConfirmationRequest(BaseModel):
    """Phase 13 signed confirmation request contract."""

    token: str
    intent_id: str
    action_type: str
    session_id: str
    intent_hash: str
    preview_payload_hash: str
    dependency_graph_hash: str
    safety_classification_hash: str
    supervision_classification: Any
    nonce: str
    correlation_id: str | None = None
    policy_version: str | None = None


ASSISTANT_CONFIRMATION_TTL_SECONDS = int(os.environ.get("ASSISTANT_CONFIRMATION_TTL_SECONDS", "180"))
ASSISTANT_CONFIRMATION_SECRET = os.environ.get(
    "ASSISTANT_CONFIRMATION_SECRET",
    getattr(auth_module, "SECRET_KEY", "assistant-confirmation-fallback"),
)
ASSISTANT_POLICY_VERSION = os.environ.get("ASSISTANT_POLICY_VERSION", "phase14.0")
ASSISTANT_POLICY_SCOPE = os.environ.get("ASSISTANT_POLICY_SCOPE", "assistant_policy_registry")
ASSISTANT_GOVERNANCE_SIGNING_SECRET = os.environ.get(
    "ASSISTANT_GOVERNANCE_SIGNING_SECRET",
    ASSISTANT_CONFIRMATION_SECRET,
)
ASSISTANT_REDIS_URL = os.environ.get("ASSISTANT_REDIS_URL", "redis://127.0.0.1:6379/0")
ASSISTANT_REDIS_PREFIX = os.environ.get("ASSISTANT_REDIS_PREFIX", "amicor:assistant:phase14")

ASSISTANT_POLICY_REGISTRY: dict[str, Any] = {
    "deny_by_default": True,
    "allowed_scopes": {"assistant-workspace"},
    "intents": {
        "preview": {"endpoint": "/api/assistant/preview", "sensitivity_tier": "low"},
        "inspect": {"endpoint": "/api/assistant/inspect", "sensitivity_tier": "moderate"},
        "simulate": {"endpoint": "/api/assistant/simulate", "sensitivity_tier": "moderate"},
    },
    "roles": {
        "admin": {
            "intent_scopes": {"preview", "inspect", "simulate"},
            "scope_scopes": {"assistant-workspace"},
            "endpoint_scopes": {"/api/assistant/preview", "/api/assistant/inspect", "/api/assistant/simulate"},
            "sensitivity_tiers": {"low", "moderate"},
        },
        "super_admin_support": {
            "intent_scopes": {"preview", "inspect", "simulate"},
            "scope_scopes": {"assistant-workspace"},
            "endpoint_scopes": {"/api/assistant/preview", "/api/assistant/inspect", "/api/assistant/simulate"},
            "sensitivity_tiers": {"low", "moderate"},
        },
        "dispatcher": {
            "intent_scopes": {"preview", "inspect", "simulate"},
            "scope_scopes": {"assistant-workspace"},
            "endpoint_scopes": {"/api/assistant/preview", "/api/assistant/inspect", "/api/assistant/simulate"},
            "sensitivity_tiers": {"low", "moderate"},
        },
        "staff": {
            "intent_scopes": {"preview", "inspect"},
            "scope_scopes": {"assistant-workspace"},
            "endpoint_scopes": {"/api/assistant/preview", "/api/assistant/inspect"},
            "sensitivity_tiers": {"low", "moderate"},
        },
        "analytics_readonly": {
            "intent_scopes": {"preview", "inspect"},
            "scope_scopes": {"assistant-workspace"},
            "endpoint_scopes": {"/api/assistant/preview", "/api/assistant/inspect"},
            "sensitivity_tiers": {"low", "moderate"},
        },
        "provider": {
            "intent_scopes": {"preview"},
            "scope_scopes": {"assistant-workspace"},
            "endpoint_scopes": {"/api/assistant/preview"},
            "sensitivity_tiers": {"low"},
        },
        "driver": {
            "intent_scopes": {"preview"},
            "scope_scopes": {"assistant-workspace"},
            "endpoint_scopes": {"/api/assistant/preview"},
            "sensitivity_tiers": {"low"},
        },
    },
}

_assistant_security_lock = threading.Lock()
_assistant_audit_chain_hash = "GENESIS"
_assistant_audit_ledger: list[dict[str, Any]] = []
_assistant_metrics: dict[str, float] = {
        "previews_generated": 0.0,
        "confirmations_verified": 0.0,
        "confirmations_rejected": 0.0,
        "redis_fail_closed": 0.0,
        "ledger_write_failures": 0.0,
        "replay_rejected": 0.0,
        "duplicate_rejected": 0.0,
        "token_mismatch_rejected": 0.0,
        "chain_integrity_failures": 0.0,
        "confirm_latency_ms_total": 0.0,
        "confirm_latency_count": 0.0,
        "redis_available": 0.0,
}
_assistant_redis_client: Any | None = None
_assistant_redis_lock = threading.Lock()
_assistant_local_replay_lock = threading.Lock()
_assistant_local_confirmation_tokens: dict[str, dict[str, Any]] = {}
_assistant_local_preview_records: dict[str, dict[str, Any]] = {}
_assistant_local_nonce_consumed: set[str] = set()
_assistant_local_request_digests: set[str] = set()
_assistant_local_intent_hashes: set[str] = set()

_ASSISTANT_REDIS_CONFIRM_CONSUME_LUA = """
local token_key = KEYS[1]
local nonce_key = KEYS[2]
local digest_key = KEYS[3]
local intent_hash_key = KEYS[4]
local now_ts = tonumber(ARGV[1])
local ttl_seconds = tonumber(ARGV[2])

if redis.call('EXISTS', token_key) == 0 then
    return 'TOKEN_NOT_ISSUED'
end

local expires_at = tonumber(redis.call('HGET', token_key, 'expires_at') or '0')
if expires_at < now_ts then
    return 'TOKEN_EXPIRED'
end

local used = redis.call('HGET', token_key, 'used')
if used == '1' then
    return 'TOKEN_ALREADY_USED'
end

if redis.call('EXISTS', nonce_key) == 1 then
    return 'NONCE_REPLAY_DETECTED'
end

if redis.call('EXISTS', digest_key) == 1 then
    return 'DUPLICATE_CONFIRMATION_REQUEST'
end

if redis.call('EXISTS', intent_hash_key) == 1 then
    return 'INTENT_HASH_REPLAY_DETECTED'
end

redis.call('HSET', token_key, 'used', '1', 'used_at', tostring(now_ts))
redis.call('SET', nonce_key, tostring(now_ts), 'EX', ttl_seconds, 'NX')
redis.call('SET', digest_key, tostring(now_ts), 'EX', ttl_seconds, 'NX')
redis.call('SET', intent_hash_key, tostring(now_ts), 'EX', ttl_seconds, 'NX')

return 'OK'
"""


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_object(data: Any) -> str:
    return _sha256_hex(_canonical_json(data))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _sign_confirmation_claims(claims: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "ASSISTANT_CONFIRM"}
    header_b64 = _b64url_encode(_canonical_json(header).encode("utf-8"))
    claims_b64 = _b64url_encode(_canonical_json(claims).encode("utf-8"))
    message = f"{header_b64}.{claims_b64}".encode("utf-8")
    signature = hmac.new(ASSISTANT_CONFIRMATION_SECRET.encode("utf-8"), message, hashlib.sha256).digest()
    return f"{header_b64}.{claims_b64}.{_b64url_encode(signature)}"


def _verify_confirmation_token(token: str) -> dict[str, Any]:
    try:
        header_b64, claims_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid confirmation token format") from exc

    message = f"{header_b64}.{claims_b64}".encode("utf-8")
    expected = hmac.new(ASSISTANT_CONFIRMATION_SECRET.encode("utf-8"), message, hashlib.sha256).digest()
    try:
        provided = _b64url_decode(signature_b64)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Confirmation token signature invalid") from exc
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Confirmation token signature invalid")

    try:
        claims = json.loads(_b64url_decode(claims_b64).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Confirmation token payload invalid") from exc

    now_ts = int(time.time())
    if int(claims.get("expires_at", 0) or 0) < now_ts:
        raise HTTPException(status_code=401, detail="Confirmation token expired")

    return claims


def _assistant_metric_increment(metric: str, amount: float = 1.0) -> None:
    with _assistant_security_lock:
        _assistant_metrics[metric] = float(_assistant_metrics.get(metric, 0.0)) + float(amount)


def _assistant_metric_set(metric: str, value: float) -> None:
    with _assistant_security_lock:
        _assistant_metrics[metric] = float(value)


def _assistant_metric_snapshot() -> dict[str, Any]:
    with _assistant_security_lock:
        raw = dict(_assistant_metrics)
    count = max(1.0, float(raw.get("confirm_latency_count", 0.0) or 0.0))
    return {
        "previews_generated": int(raw.get("previews_generated", 0.0) or 0.0),
        "confirmations_verified": int(raw.get("confirmations_verified", 0.0) or 0.0),
        "confirmations_rejected": int(raw.get("confirmations_rejected", 0.0) or 0.0),
        "redis_fail_closed": int(raw.get("redis_fail_closed", 0.0) or 0.0),
        "ledger_write_failures": int(raw.get("ledger_write_failures", 0.0) or 0.0),
        "replay_rejected": int(raw.get("replay_rejected", 0.0) or 0.0),
        "duplicate_rejected": int(raw.get("duplicate_rejected", 0.0) or 0.0),
        "token_mismatch_rejected": int(raw.get("token_mismatch_rejected", 0.0) or 0.0),
        "chain_integrity_failures": int(raw.get("chain_integrity_failures", 0.0) or 0.0),
        "confirm_avg_latency_ms": round(float(raw.get("confirm_latency_ms_total", 0.0) or 0.0) / count, 2),
        "distributed_replay_protection": bool(raw.get("redis_available", 0.0)),
        "policy_version": ASSISTANT_POLICY_VERSION,
    }


def _assistant_redis_key(kind: str, value: str) -> str:
    return f"{ASSISTANT_REDIS_PREFIX}:{kind}:{value}"


def _assistant_confirmation_guard_ttl(expires_at: int, now_ts: int) -> int:
    return max(60, int(expires_at) - int(now_ts) + 300)


def _get_assistant_redis(required: bool = True) -> Any | None:
    global _assistant_redis_client

    if _assistant_redis_client is not None:
        return _assistant_redis_client

    with _assistant_redis_lock:
        if _assistant_redis_client is not None:
            return _assistant_redis_client
        try:
            import redis  # type: ignore

            client = redis.Redis.from_url(
                ASSISTANT_REDIS_URL,
                decode_responses=True,
                socket_timeout=1.5,
                socket_connect_timeout=1.5,
            )
            client.ping()
            _assistant_redis_client = client
            _assistant_metric_set("redis_available", 1.0)
            return _assistant_redis_client
        except Exception as exc:
            _assistant_metric_set("redis_available", 0.0)
            _assistant_metric_increment("redis_fail_closed")
            logger.error("Assistant Redis unavailable: %s", exc)
            if required:
                raise HTTPException(status_code=503, detail="Distributed replay protection unavailable") from exc
            return None


def _cleanup_assistant_local_replay_store(now_ts: int) -> None:
    with _assistant_local_replay_lock:
        for token_id, record in list(_assistant_local_confirmation_tokens.items()):
            if int(record.get("expires_at", 0) or 0) < now_ts:
                _assistant_local_confirmation_tokens.pop(token_id, None)
        for intent_id, record in list(_assistant_local_preview_records.items()):
            if int(record.get("expires_at", 0) or 0) < now_ts:
                _assistant_local_preview_records.pop(intent_id, None)


def _local_store_confirmation_token(claims: dict[str, Any], signed_token: str, policy: dict[str, Any], correlation_id: str) -> None:
    token_id = str(claims.get("jti") or "").strip()
    if not token_id:
        raise HTTPException(status_code=500, detail="Missing confirmation token id")
    now_ts = int(time.time())
    expires_at = int(claims.get("expires_at", now_ts))
    ttl = _assistant_confirmation_guard_ttl(expires_at, now_ts)
    _cleanup_assistant_local_replay_store(now_ts)
    with _assistant_local_replay_lock:
        _assistant_local_confirmation_tokens[token_id] = {
            "token_id": token_id,
            "intent_id": str(claims.get("intent_id") or ""),
            "action_type": str(claims.get("action_type") or ""),
            "user_id": str(claims.get("user_id") or ""),
            "session_id": str(claims.get("session_id") or ""),
            "intent_hash": str(claims.get("intent_hash") or ""),
            "nonce": str(claims.get("nonce") or ""),
            "issued_at": int(claims.get("issued_at", now_ts)),
            "expires_at": expires_at,
            "dry_run_only": "1" if bool(claims.get("dry_run_only")) else "0",
            "supervision_classification": str(claims.get("supervision_classification") or ""),
            "policy_version": str(policy.get("policy_version") or ASSISTANT_POLICY_VERSION),
            "policy_scope": str(policy.get("policy_scope") or ASSISTANT_POLICY_SCOPE),
            "policy_decision": str(policy.get("policy_state") or "ALLOWED"),
            "sensitivity_tier": str(policy.get("sensitivity_tier") or "unknown"),
            "correlation_id": correlation_id,
            "signed_token": signed_token,
            "used": "0",
            "ttl": ttl,
        }


def _local_store_preview_record(intent_id: str, payload: dict[str, Any], expires_at: int) -> None:
    _cleanup_assistant_local_replay_store(int(time.time()))
    with _assistant_local_replay_lock:
        record = dict(payload)
        record["expires_at"] = int(expires_at)
        _assistant_local_preview_records[str(intent_id)] = record


def _local_get_confirmation_token(token_id: str) -> dict[str, Any] | None:
    _cleanup_assistant_local_replay_store(int(time.time()))
    with _assistant_local_replay_lock:
        record = _assistant_local_confirmation_tokens.get(str(token_id))
        return dict(record) if record else None


def _local_get_preview_record(intent_id: str) -> dict[str, Any] | None:
    _cleanup_assistant_local_replay_store(int(time.time()))
    with _assistant_local_replay_lock:
        record = _assistant_local_preview_records.get(str(intent_id))
        return dict(record) if record else None


def _local_consume_confirmation_guards(token_id: str, nonce: str, request_hash: str, intent_hash: str, expires_at: int) -> str:
    now_ts = int(time.time())
    _cleanup_assistant_local_replay_store(now_ts)
    with _assistant_local_replay_lock:
        token = _assistant_local_confirmation_tokens.get(str(token_id))
        if not token:
            return "TOKEN_NOT_FOUND"
        if int(token.get("expires_at", 0) or 0) < now_ts:
            return "TOKEN_EXPIRED"
        if str(token.get("used", "0")) == "1":
            return "TOKEN_ALREADY_CONSUMED"
        if str(nonce) in _assistant_local_nonce_consumed:
            return "NONCE_REPLAY_DETECTED"
        if str(request_hash) in _assistant_local_request_digests:
            return "INTENT_HASH_REPLAY_DETECTED"
        if str(intent_hash) in _assistant_local_intent_hashes:
            return "INTENT_HASH_REPLAY_DETECTED"
        token["used"] = "1"
        _assistant_local_nonce_consumed.add(str(nonce))
        _assistant_local_request_digests.add(str(request_hash))
        _assistant_local_intent_hashes.add(str(intent_hash))
        return "OK"


def _redis_store_confirmation_token(claims: dict[str, Any], signed_token: str, policy: dict[str, Any], correlation_id: str) -> None:
    client = _get_assistant_redis(required=False)
    if client is None:
        _local_store_confirmation_token(claims, signed_token, policy, correlation_id)
        return
    token_id = str(claims.get("jti") or "").strip()
    if not token_id:
        raise HTTPException(status_code=500, detail="Missing confirmation token id")

    now_ts = int(time.time())
    expires_at = int(claims.get("expires_at", now_ts))
    ttl = _assistant_confirmation_guard_ttl(expires_at, now_ts)
    token_key = _assistant_redis_key("token", token_id)
    client.hset(
        token_key,
        mapping={
            "token_id": token_id,
            "intent_id": str(claims.get("intent_id") or ""),
            "action_type": str(claims.get("action_type") or ""),
            "user_id": str(claims.get("user_id") or ""),
            "session_id": str(claims.get("session_id") or ""),
            "intent_hash": str(claims.get("intent_hash") or ""),
            "nonce": str(claims.get("nonce") or ""),
            "issued_at": str(int(claims.get("issued_at", now_ts))),
            "expires_at": str(expires_at),
            "dry_run_only": "1" if bool(claims.get("dry_run_only")) else "0",
            "supervision_classification": str(claims.get("supervision_classification") or ""),
            "policy_version": str(policy.get("policy_version") or ASSISTANT_POLICY_VERSION),
            "policy_scope": str(policy.get("policy_scope") or ASSISTANT_POLICY_SCOPE),
            "policy_decision": str(policy.get("policy_state") or "ALLOWED"),
            "sensitivity_tier": str(policy.get("sensitivity_tier") or "unknown"),
            "correlation_id": correlation_id,
            "signed_token": signed_token,
            "used": "0",
        },
    )
    client.expire(token_key, ttl)


def _redis_store_preview_record(intent_id: str, payload: dict[str, Any], expires_at: int) -> None:
    client = _get_assistant_redis(required=False)
    if client is None:
        _local_store_preview_record(intent_id, payload, expires_at)
        return
    now_ts = int(time.time())
    ttl = _assistant_confirmation_guard_ttl(expires_at, now_ts)
    preview_key = _assistant_redis_key("preview", intent_id)
    client.set(preview_key, _canonical_json(payload), ex=ttl)


def _redis_get_confirmation_token(token_id: str) -> dict[str, Any] | None:
    client = _get_assistant_redis(required=False)
    if client is None:
        return _local_get_confirmation_token(token_id)
    token_key = _assistant_redis_key("token", token_id)
    data = client.hgetall(token_key)
    return data or None


def _redis_get_preview_record(intent_id: str) -> dict[str, Any] | None:
    client = _get_assistant_redis(required=False)
    if client is None:
        return _local_get_preview_record(intent_id)
    preview_key = _assistant_redis_key("preview", intent_id)
    raw = client.get(preview_key)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def _redis_consume_confirmation_guards(token_id: str, nonce: str, request_hash: str, intent_hash: str, expires_at: int) -> str:
    client = _get_assistant_redis(required=False)
    if client is None:
        return _local_consume_confirmation_guards(token_id, nonce, request_hash, intent_hash, expires_at)
    now_ts = int(time.time())
    ttl = _assistant_confirmation_guard_ttl(expires_at, now_ts)
    token_key = _assistant_redis_key("token", token_id)
    nonce_key = _assistant_redis_key("nonce", nonce)
    digest_key = _assistant_redis_key("confirm_digest", request_hash)
    intent_hash_key = _assistant_redis_key("intent_hash", intent_hash)
    result = client.eval(
        _ASSISTANT_REDIS_CONFIRM_CONSUME_LUA,
        4,
        token_key,
        nonce_key,
        digest_key,
        intent_hash_key,
        str(now_ts),
        str(ttl),
    )
    return str(result or "")


def _compute_ledger_chain_hash(previous_event_hash: str, canonical_payload_hash: str, event_signature: str, sequence: int) -> str:
    return _hash_object(
        {
            "previous_event_hash": previous_event_hash,
            "canonical_payload_hash": canonical_payload_hash,
            "event_signature": event_signature,
            "sequence": int(sequence),
        }
    )


def _verify_assistant_ledger_tail(max_events: int = 250) -> dict[str, Any]:
    db = SessionLocal()
    try:
        rows = (
            db.query(AssistantGovernanceLedger)
            .order_by(AssistantGovernanceLedger.sequence.desc())
            .limit(max_events)
            .all()
        )
        rows = list(reversed(rows))
    finally:
        db.close()

    verified = 0
    valid = True
    previous_hash = str(rows[0].previous_event_hash) if rows else "GENESIS"
    last_hash = "GENESIS"

    for row in rows:
        expected_sig = hmac.new(
            ASSISTANT_GOVERNANCE_SIGNING_SECRET.encode("utf-8"),
            str(row.canonical_payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if str(row.event_signature) != expected_sig:
            valid = False
            break
        expected_hash = _compute_ledger_chain_hash(
            str(row.previous_event_hash),
            str(row.canonical_payload_hash),
            str(row.event_signature),
            int(row.sequence),
        )
        if str(row.current_event_hash) != expected_hash:
            valid = False
            break
        if str(row.previous_event_hash) != previous_hash:
            valid = False
            break
        verified += 1
        previous_hash = str(row.current_event_hash)
        last_hash = str(row.current_event_hash)

    return {
        "verified": bool(valid),
        "verified_events": int(verified),
        "last_event_hash": last_hash,
    }


def _persist_assistant_preview_record(record: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        existing = (
            db.query(AssistantPreviewRecord)
            .filter(AssistantPreviewRecord.intent_id == str(record["intent_id"]))
            .first()
        )
        if existing is None:
            existing = AssistantPreviewRecord(
                intent_id=str(record["intent_id"]),
                token_id=str(record["token_id"]),
                correlation_id=str(record["correlation_id"]),
                user_id=str(record["user_id"]),
                role=str(record["role"]),
                action_type=str(record["action_type"]),
                session_id=str(record["session_id"]),
                supervision_classification=str(record["supervision_classification"]),
                policy_version=str(record["policy_version"]),
                policy_scope=str(record["policy_scope"]),
                policy_decision=str(record["policy_decision"]),
                sensitivity_tier=str(record["sensitivity_tier"]),
                nonce=str(record["nonce"]),
                intent_hash=str(record["intent_hash"]),
                preview_payload_hash=str(record["preview_payload_hash"]),
                dependency_graph_hash=str(record["dependency_graph_hash"]),
                safety_classification_hash=str(record["safety_classification_hash"]),
                preview_payload_json=str(record["preview_payload_json"]),
                issued_at=int(record["issued_at"]),
                expires_at=int(record["expires_at"]),
            )
            db.add(existing)
        else:
            existing.preview_payload_json = str(record["preview_payload_json"])
            existing.expires_at = int(record["expires_at"])
        db.commit()
    except Exception as exc:
        db.rollback()
        _assistant_metric_increment("ledger_write_failures")
        raise HTTPException(status_code=503, detail="Durable preview persistence unavailable") from exc
    finally:
        db.close()


def _mark_assistant_preview_confirmed(intent_id: str, confirmed_at: int) -> None:
    db = SessionLocal()
    try:
        existing = (
            db.query(AssistantPreviewRecord)
            .filter(AssistantPreviewRecord.intent_id == str(intent_id))
            .first()
        )
        if existing is not None:
            existing.confirmed_at = datetime.fromtimestamp(int(confirmed_at), tz=timezone.utc)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _cleanup_assistant_security_state(now_ts: int) -> None:
    _ = now_ts
    # TTL cleanup is delegated to Redis key expiry and SQL retention.
    return None


def _append_assistant_ledger_event(event_type: str, user: UserContext, details: dict[str, Any]) -> dict[str, Any]:
    global _assistant_audit_chain_hash

    policy_version = str(details.get("policy_version") or ASSISTANT_POLICY_VERSION)
    policy_scope = str(details.get("policy_scope") or ASSISTANT_POLICY_SCOPE)
    policy_decision = str(details.get("policy_decision") or "ALLOWED")
    sensitivity_tier = str(details.get("sensitivity_tier") or "unknown")
    supervision_classification = str(details.get("supervision_classification") or "supervision_enforced")
    correlation_id = str(details.get("correlation_id") or f"corr-{int(time.time() * 1000)}-{secrets.token_hex(4)}")
    session_id = str(details.get("session_id") or "") or None
    intent_id = str(details.get("intent_id") or "") or None
    token_id = str(details.get("token_id") or "") or None
    action_type = str(details.get("action_type") or "") or None

    immutable_event = {
        "event_type": str(event_type or "assistant_event"),
        "recorded_at": int(time.time()),
        "user_id": str(user.user_id),
        "role": str(user.role),
        "details": details,
        "correlation_id": correlation_id,
        "policy_version": policy_version,
        "policy_scope": policy_scope,
        "policy_decision": policy_decision,
        "sensitivity_tier": sensitivity_tier,
        "supervision_classification": supervision_classification,
        "dry_run_only": True,
        "execution_disabled": True,
        "workflow_dispatch": False,
    }

    canonical_payload = _canonical_json(immutable_event)
    canonical_payload_hash = _sha256_hex(canonical_payload)
    event_signature = hmac.new(
        ASSISTANT_GOVERNANCE_SIGNING_SECRET.encode("utf-8"),
        canonical_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    db = SessionLocal()
    try:
        last = db.query(AssistantGovernanceLedger).order_by(AssistantGovernanceLedger.sequence.desc()).first()
        if last is None:
            sequence = 1
            previous_event_hash = "GENESIS"
        else:
            expected_last_hash = _compute_ledger_chain_hash(
                str(last.previous_event_hash),
                str(last.canonical_payload_hash),
                str(last.event_signature),
                int(last.sequence),
            )
            if expected_last_hash != str(last.current_event_hash):
                _assistant_metric_increment("chain_integrity_failures")
                raise HTTPException(status_code=503, detail="Assistant governance ledger integrity failure")
            sequence = int(last.sequence) + 1
            previous_event_hash = str(last.current_event_hash)

        current_event_hash = _compute_ledger_chain_hash(
            previous_event_hash,
            canonical_payload_hash,
            event_signature,
            sequence,
        )

        db_record = AssistantGovernanceLedger(
            sequence=sequence,
            event_id=secrets.token_hex(16),
            correlation_id=correlation_id,
            event_type=str(event_type or "assistant_event"),
            user_id=str(user.user_id),
            role=str(user.role),
            session_id=session_id,
            intent_id=intent_id,
            action_type=action_type,
            token_id=token_id,
            policy_version=policy_version,
            policy_scope=policy_scope,
            policy_decision=policy_decision,
            sensitivity_tier=sensitivity_tier,
            supervision_classification=supervision_classification,
            dry_run_only=True,
            execution_disabled=True,
            workflow_dispatch=False,
            canonical_payload=canonical_payload,
            canonical_payload_hash=canonical_payload_hash,
            previous_event_hash=previous_event_hash,
            current_event_hash=current_event_hash,
            event_signature=event_signature,
        )
        db.add(db_record)
        db.commit()
    except HTTPException:
        db.rollback()
        _assistant_metric_increment("ledger_write_failures")
        raise
    except Exception as exc:
        db.rollback()
        _assistant_metric_increment("ledger_write_failures")
        logger.error("Assistant governance ledger write failed: %s", exc)
        raise HTTPException(status_code=503, detail="Assistant governance ledger unavailable") from exc
    finally:
        db.close()

    with _assistant_security_lock:
        _assistant_audit_chain_hash = current_event_hash
        ledger_entry = {
            "sequence": sequence,
            "previous_chain_hash": previous_event_hash,
            "chain_hash": current_event_hash,
            **immutable_event,
        }
        _assistant_audit_ledger.append(ledger_entry)

    return ledger_entry


def _evaluate_structured_policy(role: str, intent: str, scope: str, endpoint: str) -> dict[str, Any]:
    normalized_role = str(role or "staff").strip().lower()
    normalized_intent = str(intent or "preview").strip().lower()
    normalized_scope = str(scope or "assistant-workspace").strip().lower()
    normalized_endpoint = str(endpoint or "").strip().lower()

    reasons: list[str] = []
    policy_state = "ALLOWED"

    role_policy = ASSISTANT_POLICY_REGISTRY["roles"].get(normalized_role)
    intent_policy = ASSISTANT_POLICY_REGISTRY["intents"].get(normalized_intent)

    if role_policy is None:
        policy_state = "BLOCKED"
        reasons.append("ROLE_UNREGISTERED_DENY_BY_DEFAULT")

    if intent_policy is None:
        policy_state = "BLOCKED"
        reasons.append("INTENT_UNREGISTERED_DENY_BY_DEFAULT")

    if normalized_scope not in ASSISTANT_POLICY_REGISTRY["allowed_scopes"]:
        policy_state = "BLOCKED"
        reasons.append("SCOPE_UNREGISTERED_DENY_BY_DEFAULT")

    if role_policy is not None and normalized_scope not in role_policy["scope_scopes"]:
        policy_state = "BLOCKED"
        reasons.append("ROLE_SCOPE_DENIED")

    if role_policy is not None and normalized_intent not in role_policy["intent_scopes"]:
        policy_state = "BLOCKED"
        reasons.append("ROLE_INTENT_DENIED")

    if intent_policy is not None and normalized_endpoint != str(intent_policy["endpoint"]).lower():
        policy_state = "BLOCKED"
        reasons.append("ENDPOINT_INTENT_MISMATCH")

    if role_policy is not None and normalized_endpoint not in {
        str(item).lower() for item in role_policy["endpoint_scopes"]
    }:
        policy_state = "BLOCKED"
        reasons.append("ROLE_ENDPOINT_DENIED")

    if intent_policy is not None:
        sensitivity_tier = str(intent_policy["sensitivity_tier"])
    else:
        sensitivity_tier = "unknown"

    if role_policy is not None and sensitivity_tier not in role_policy["sensitivity_tiers"]:
        policy_state = "BLOCKED"
        reasons.append("SENSITIVITY_TIER_DENIED")

    if not reasons:
        reasons.append("POLICY_REGISTRY_ALLOW")

    return {
        "policy_state": policy_state,
        "policy_decision": policy_state,
        "reason_codes": reasons,
        "role": normalized_role,
        "intent": normalized_intent,
        "scope": normalized_scope,
        "endpoint": normalized_endpoint,
        "sensitivity_tier": sensitivity_tier,
        "policy_version": ASSISTANT_POLICY_VERSION,
        "policy_scope": ASSISTANT_POLICY_SCOPE,
        "supervision_required": True,
        "dry_run_only": True,
        "execution_disabled": True,
        "autonomous_execution": False,
        "workflow_dispatch": False,
    }


def _build_dependency_graph() -> dict[str, Any]:
    return {
        "nodes": [
            "assistant_workspace",
            "supervision_api",
            "runtime_governor",
            "telemetry_pipeline",
            "websocket_fabric",
        ],
        "edges": [
            ["assistant_workspace", "supervision_api"],
            ["assistant_workspace", "runtime_governor"],
            ["assistant_workspace", "telemetry_pipeline"],
            ["assistant_workspace", "websocket_fabric"],
        ],
        "mutating_edges": [],
        "execution_authority": False,
    }


def _build_intent_hash_payload(intent_id: str, intent: str, prompt: str, role: str, scope: str, session_id: str) -> dict[str, Any]:
    return {
        "intent_id": intent_id,
        "intent": intent,
        "prompt": prompt,
        "role": role,
        "scope": scope,
        "session_id": session_id,
        "dry_run_only": True,
    }


def _enforce_assistant_supervision(
    endpoint_intent: str,
    endpoint_path: str,
    request: AssistantBridgeRequest,
    user: UserContext,
) -> dict[str, Any]:
    normalized_intent = str(endpoint_intent or "preview").strip().lower()
    normalized_scope = str(request.scope or "assistant-workspace").strip().lower()
    effective_role = str(user.role or "staff").strip().lower()
    requested_role = str(request.role or effective_role).strip().lower()

    if requested_role != effective_role:
        _append_assistant_ledger_event(
            "blocked_action_attempted",
            user,
            {
                "reason": "REQUESTED_ROLE_MISMATCH",
                "requested_role": requested_role,
                "effective_role": effective_role,
                "intent": normalized_intent,
                "scope": normalized_scope,
                "endpoint": endpoint_path,
            },
        )
        raise HTTPException(status_code=403, detail="Role mismatch for supervised assistant preview")

    if str(request.intent or normalized_intent).strip().lower() not in {normalized_intent, ""}:
        _append_assistant_ledger_event(
            "blocked_action_attempted",
            user,
            {
                "reason": "INTENT_PAYLOAD_MISMATCH",
                "payload_intent": str(request.intent),
                "endpoint_intent": normalized_intent,
                "scope": normalized_scope,
                "endpoint": endpoint_path,
            },
        )
        raise HTTPException(status_code=400, detail="Intent payload mismatch for preview endpoint")

    policy = _evaluate_structured_policy(
        role=effective_role,
        intent=normalized_intent,
        scope=normalized_scope,
        endpoint=endpoint_path,
    )

    if policy["policy_state"] == "BLOCKED":
        _append_assistant_ledger_event(
            "blocked_action_attempted",
            user,
            {
                "reason_codes": policy["reason_codes"],
                "intent": normalized_intent,
                "scope": normalized_scope,
                "endpoint": endpoint_path,
            },
        )
        raise HTTPException(status_code=403, detail="Assistant preview blocked by policy registry")

    if not policy["dry_run_only"] or not policy["execution_disabled"]:
        _append_assistant_ledger_event(
            "blocked_action_attempted",
            user,
            {
                "reason": "DRY_RUN_ENFORCEMENT_ASSERTION_FAILED",
                "intent": normalized_intent,
                "scope": normalized_scope,
                "endpoint": endpoint_path,
            },
        )
        raise HTTPException(status_code=500, detail="Dry-run enforcement assertion failed")

    return {
        "intent": normalized_intent,
        "scope": normalized_scope,
        "effective_role": effective_role,
        "session_id": str(request.session_id or request.context.get("session_id") or "").strip() or f"sess-{user.user_id}",
        "policy": policy,
    }


def _issue_signed_confirmation_token(
    user: UserContext,
    intent_id: str,
    action_type: str,
    session_id: str,
    supervision_classification: str,
    intent_hash: str,
    policy: dict[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    now_ts = int(time.time())
    expires_at = now_ts + ASSISTANT_CONFIRMATION_TTL_SECONDS
    nonce = secrets.token_hex(16)
    token_id = secrets.token_hex(12)

    claims = {
        "jti": token_id,
        "intent_id": intent_id,
        "action_type": action_type,
        "issued_at": now_ts,
        "expires_at": expires_at,
        "session_id": session_id,
        "user_id": user.user_id,
        "supervision_classification": supervision_classification,
        "dry_run_only": True,
        "intent_hash": intent_hash,
        "nonce": nonce,
        "correlation_id": correlation_id,
        "policy_version": str(policy.get("policy_version") or ASSISTANT_POLICY_VERSION),
        "policy_scope": str(policy.get("policy_scope") or ASSISTANT_POLICY_SCOPE),
        "policy_decision": str(policy.get("policy_state") or "ALLOWED"),
        "sensitivity_tier": str(policy.get("sensitivity_tier") or "unknown"),
    }
    signed_token = _sign_confirmation_claims(claims)
    _redis_store_confirmation_token(claims, signed_token, policy, correlation_id)

    return {
        "signed_token": signed_token,
        "token_id": token_id,
        "intent_id": intent_id,
        "action_type": action_type,
        "issued_at": now_ts,
        "expires_at": expires_at,
        "session_id": session_id,
        "supervision_classification": supervision_classification,
        "policy_version": str(policy.get("policy_version") or ASSISTANT_POLICY_VERSION),
        "policy_scope": str(policy.get("policy_scope") or ASSISTANT_POLICY_SCOPE),
        "policy_decision": str(policy.get("policy_state") or "ALLOWED"),
        "sensitivity_tier": str(policy.get("sensitivity_tier") or "unknown"),
        "correlation_id": correlation_id,
        "dry_run_only": True,
        "nonce": nonce,
    }


def _build_assistant_dry_run_payload(
    endpoint_intent: str,
    endpoint_path: str,
    request: AssistantBridgeRequest,
    user: UserContext,
) -> dict[str, Any]:
    _cleanup_assistant_security_state(int(time.time()))

    enforcement = _enforce_assistant_supervision(
        endpoint_intent=endpoint_intent,
        endpoint_path=endpoint_path,
        request=request,
        user=user,
    )

    intent = enforcement["intent"]
    prompt = str(request.prompt or "").strip()
    role = enforcement["effective_role"]
    scope = enforcement["scope"]
    session_id = enforcement["session_id"]
    policy = enforcement["policy"]
    supervision_status = "supervision_enforced"
    intent_id = f"intent-{int(time.time() * 1000)}-{secrets.token_hex(4)}"
    correlation_id = str(request.context.get("correlation_id") or f"corr-{int(time.time() * 1000)}-{secrets.token_hex(4)}")

    operational_awareness: dict[str, Any] = {
        "enabled": False,
        "preview_only": True,
        "read_only": True,
        "supervision_safe": True,
        "execution_disabled": True,
    }
    prompt_lc = prompt.lower()
    if any(token in prompt_lc for token in ("ride", "driver", "provider", "workflow", "operations", "delayed", "available")):
        try:
            from app.modules.health_isf.operational_workflow_orchestration import build_assistant_operational_awareness

            org_id = str(getattr(user, "organization_id", "") or "")
            if org_id:
                with SessionLocal() as db:
                    operational_awareness = build_assistant_operational_awareness(
                        db,
                        organization_id=org_id,
                        prompt=prompt,
                        role=role,
                    )
        except Exception:
            operational_awareness = {
                "enabled": False,
                "preview_only": True,
                "read_only": True,
                "supervision_safe": True,
                "execution_disabled": True,
            }

    dependency_graph = _build_dependency_graph()
    requested_action_summary = {
        "intent_id": intent_id,
        "intent": intent,
        "prompt_excerpt": prompt[:180],
        "role": role,
        "scope": scope,
        "session_id": session_id,
        "correlation_id": correlation_id,
        "policy_version": policy["policy_version"],
        "policy_scope": policy["policy_scope"],
        "policy_decision": policy["policy_decision"],
        "sensitivity_tier": policy["sensitivity_tier"],
        "mode": "dry_run_preview_only",
    }

    safety_classification = {
        "policy_state": policy["policy_state"],
        "reason_codes": policy["reason_codes"],
        "policy_version": policy["policy_version"],
        "policy_scope": policy["policy_scope"],
        "policy_decision": policy["policy_decision"],
        "sensitivity_tier": policy["sensitivity_tier"],
        "supervision_required": True,
        "autonomous_execution": False,
        "workflow_dispatch": False,
        "execution_disabled": True,
        "dry_run_only": True,
    }

    dependency_awareness = {
        "systems": dependency_graph["nodes"],
        "database_mutation": False,
        "orchestration_mutation": False,
        "memory_persistence": False,
        "dispatch_actions": False,
    }

    supervision_classification = {
        "classification": supervision_status,
        "requires_human_confirmation": True,
        "contract_compatibility": "preserved",
        "role_validation": True,
        "intent_validation": True,
        "scope_validation": True,
        "dry_run_enforced": True,
        "execution_disabled_assertion": True,
    }

    estimated_impact = {
        "runtime_impact": "none",
        "state_mutation": "none",
        "telemetry_impact": "read_only_preview",
        "user_visible_effect": "preview_card_only",
    }

    preview_card = {
        "proposed_operation": intent,
        "affected_systems": [
            "assistant_workspace",
            "supervision_api",
            "runtime_telemetry",
            "operational_workflow_orchestration",
        ],
        "supervision_classification": supervision_status,
        "runtime_impact": "no_runtime_mutation",
        "allowed_status": safety_classification["policy_state"],
        "reason_codes": safety_classification["reason_codes"],
    }

    intent_hash_payload = _build_intent_hash_payload(
        intent_id=intent_id,
        intent=intent,
        prompt=prompt,
        role=role,
        scope=scope,
        session_id=session_id,
    )
    intent_hash = _hash_object(intent_hash_payload)
    dependency_graph_hash = _hash_object(dependency_graph)
    safety_classification_hash = _hash_object(safety_classification)

    payload_without_integrity = normalize_assistant_preview_payload({
        "requested_action_summary": requested_action_summary,
        "operational_awareness": operational_awareness,
        "dependency_awareness": dependency_awareness,
        "supervision_classification": supervision_classification,
        "estimated_impact": estimated_impact,
        "safety_classification": safety_classification,
        "preview_card": preview_card,
        "endpoint": endpoint_path,
        "dry_run_only": True,
        "execution_disabled": True,
    })
    preview_payload_hash = _hash_object(payload_without_integrity)

    integrity = {
        "intent_hash": intent_hash,
        "preview_payload_hash": preview_payload_hash,
        "dependency_graph_hash": dependency_graph_hash,
        "safety_classification_hash": safety_classification_hash,
    }

    confirmation = _issue_signed_confirmation_token(
        user=user,
        intent_id=intent_id,
        action_type=intent,
        session_id=session_id,
        supervision_classification=supervision_status,
        intent_hash=intent_hash,
        policy=policy,
        correlation_id=correlation_id,
    )

    payload = normalize_assistant_preview_payload({
        **payload_without_integrity,
        "integrity": integrity,
        "confirmation": confirmation,
        "governance": {
            "durable_verified_preview": True,
            "audit_chain_active": True,
            "distributed_replay_protection": True,
            "policy_version": policy["policy_version"],
            "policy_scope": policy["policy_scope"],
            "policy_decision": policy["policy_decision"],
            "sensitivity_tier": policy["sensitivity_tier"],
            "correlation_id": correlation_id,
        },
        "security_state": {
            "verified_preview": False,
            "signed_confirmation": True,
            "token_expires_in_seconds": max(0, int(confirmation["expires_at"]) - int(time.time())),
            "dry_run_only": True,
            "execution_disabled": True,
            "supervision_enforced": True,
            "durable_verified_preview": True,
            "audit_chain_active": True,
            "distributed_replay_protection": True,
            "policy_version": policy["policy_version"],
            "correlation_id": correlation_id,
        },
    })

    preview_record = {
        "intent_id": intent_id,
        "token_id": str(confirmation.get("token_id") or ""),
        "correlation_id": correlation_id,
        "user_id": str(user.user_id),
        "role": str(user.role),
        "action_type": intent,
        "session_id": session_id,
        "supervision_classification": supervision_status,
        "policy_version": policy["policy_version"],
        "policy_scope": policy["policy_scope"],
        "policy_decision": policy["policy_decision"],
        "sensitivity_tier": policy["sensitivity_tier"],
        "nonce": str(confirmation["nonce"]),
        "intent_hash": intent_hash,
        "preview_payload_hash": preview_payload_hash,
        "dependency_graph_hash": dependency_graph_hash,
        "safety_classification_hash": safety_classification_hash,
        "preview_payload_json": _canonical_json(payload),
        "issued_at": int(confirmation["issued_at"]),
        "expires_at": int(confirmation["expires_at"]),
    }
    _persist_assistant_preview_record(preview_record)
    _redis_store_preview_record(intent_id=intent_id, payload=preview_record, expires_at=int(confirmation["expires_at"]))
    _assistant_metric_increment("previews_generated")

    _append_assistant_ledger_event(
        "preview_generated",
        user,
        {
            "intent_id": intent_id,
            "action_type": intent,
            "session_id": session_id,
            "integrity": integrity,
            "endpoint": endpoint_path,
            "policy_version": policy["policy_version"],
            "policy_scope": policy["policy_scope"],
            "policy_decision": policy["policy_decision"],
            "sensitivity_tier": policy["sensitivity_tier"],
            "supervision_classification": supervision_status,
            "correlation_id": correlation_id,
            "token_id": str(confirmation.get("token_id") or ""),
        },
    )
    _append_assistant_ledger_event(
        "confirmation_issued",
        user,
        {
            "intent_id": intent_id,
            "action_type": intent,
            "session_id": session_id,
            "expires_at": confirmation["expires_at"],
            "dry_run_only": True,
            "policy_version": policy["policy_version"],
            "policy_scope": policy["policy_scope"],
            "policy_decision": policy["policy_decision"],
            "sensitivity_tier": policy["sensitivity_tier"],
            "supervision_classification": supervision_status,
            "correlation_id": correlation_id,
            "token_id": str(confirmation.get("token_id") or ""),
        },
    )

    return payload


def _build_confirmation_request_hash(request: AssistantConfirmationRequest) -> str:
    return _hash_object(
        {
            "intent_id": request.intent_id,
            "action_type": request.action_type,
            "session_id": request.session_id,
            "intent_hash": request.intent_hash,
            "preview_payload_hash": request.preview_payload_hash,
            "dependency_graph_hash": request.dependency_graph_hash,
            "safety_classification_hash": request.safety_classification_hash,
            "supervision_classification": request.supervision_classification,
            "nonce": request.nonce,
            "correlation_id": request.correlation_id,
            "policy_version": request.policy_version,
        }
    )


@app.post("/api/assistant/preview", tags=["assistant"])
def assistant_preview(
    request: AssistantBridgeRequest,
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Phase 13 dry-run preview endpoint with signed confirmation token issuance."""

    log_operational_event(
        user_id=str(user.user_id),
        role=str(user.role),
        event_type="assistant",
        event_name="preview_requested",
        status="success",
        session_id=str(request.session_id),
        payload={"intent": str(request.intent), "scope": str(request.scope or "assistant-workspace")},
    )

    return _build_assistant_dry_run_payload(
        endpoint_intent="preview",
        endpoint_path="/api/assistant/preview",
        request=request,
        user=user,
    )


@app.post("/api/assistant/simulate", tags=["assistant"])
def assistant_simulate(
    request: AssistantBridgeRequest,
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Phase 13 simulation endpoint with signed confirmation token issuance."""

    return _build_assistant_dry_run_payload(
        endpoint_intent="simulate",
        endpoint_path="/api/assistant/simulate",
        request=request,
        user=user,
    )


@app.post("/api/assistant/inspect", tags=["assistant"])
def assistant_inspect(
    request: AssistantBridgeRequest,
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Phase 13 inspect endpoint with signed confirmation token issuance."""

    return _build_assistant_dry_run_payload(
        endpoint_intent="inspect",
        endpoint_path="/api/assistant/inspect",
        request=request,
        user=user,
    )


@app.post("/api/assistant/confirm", tags=["assistant"])
def assistant_confirm(
    request: AssistantConfirmationRequest,
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Signed confirmation verification endpoint with Phase 36 execution foundation hooks."""

    started_at = time.perf_counter()
    _cleanup_assistant_security_state(int(time.time()))

    claims = _verify_confirmation_token(request.token)
    request_hash = _build_confirmation_request_hash(request)
    now_ts = int(time.time())

    token_id = str(claims.get("jti", "")).strip()
    correlation_id = str(claims.get("correlation_id") or "").strip() or f"corr-{int(time.time() * 1000)}-{secrets.token_hex(4)}"
    policy_version = str(claims.get("policy_version") or ASSISTANT_POLICY_VERSION)
    policy_scope = str(claims.get("policy_scope") or ASSISTANT_POLICY_SCOPE)
    policy_decision = str(claims.get("policy_decision") or "ALLOWED")
    sensitivity_tier = str(claims.get("sensitivity_tier") or "unknown")
    supervision_classification = normalize_supervision_classification(request.supervision_classification)

    if not token_id:
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "TOKEN_ID_MISSING",
                "request_hash": request_hash,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=401, detail="Confirmation token id missing")

    if bool(claims.get("dry_run_only")) is not True:
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "DRY_RUN_CLAIM_MISSING",
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=403, detail="Confirmation token not scoped to dry-run only")

    issued = _redis_get_confirmation_token(token_id)

    if not issued:
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "TOKEN_NOT_ISSUED",
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=401, detail="Confirmation token not issued")

    if str(issued.get("used") or "0") == "1":
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("replay_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "TOKEN_ALREADY_USED",
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Confirmation token already consumed")

    if int(claims.get("expires_at", 0) or 0) < now_ts:
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "token_expired",
            user,
            {
                "token_id": token_id,
                "intent_id": claims.get("intent_id"),
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=401, detail="Confirmation token expired")

    intent_id = str(request.intent_id).strip()
    preview_record = _redis_get_preview_record(intent_id)

    if not preview_record:
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "INTENT_RECORD_MISSING",
                "intent_id": intent_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=404, detail="Intent preview record not found")

    expected_user_id = str(claims.get("user_id", "")).strip()
    if expected_user_id != str(user.user_id):
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("token_mismatch_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "USER_BINDING_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=403, detail="Confirmation token user binding mismatch")

    if str(request.action_type).strip().lower() != str(claims.get("action_type", "")).strip().lower():
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("token_mismatch_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "ACTION_TYPE_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Action type mismatch")

    if str(request.session_id).strip() != str(claims.get("session_id", "")).strip():
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("token_mismatch_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "SESSION_BINDING_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Session binding mismatch")

    if str(request.intent_hash).strip() != str(claims.get("intent_hash", "")).strip():
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("token_mismatch_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "INTENT_HASH_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Intent hash mismatch")

    if str(request.intent_hash).strip() != str(preview_record.get("intent_hash")):
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "PREVIEW_INTENT_HASH_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Preview payload hash mismatch")

    if str(request.preview_payload_hash).strip() != str(preview_record.get("preview_payload_hash")):
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "PREVIEW_HASH_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Preview payload hash mismatch")

    if str(request.dependency_graph_hash).strip() != str(preview_record.get("dependency_graph_hash")):
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "DEPENDENCY_HASH_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Dependency graph hash mismatch")

    if str(request.safety_classification_hash).strip() != str(preview_record.get("safety_classification_hash")):
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "SAFETY_HASH_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Safety classification hash mismatch")

    if supervision_classification != str(preview_record.get("supervision_classification")):
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "SUPERVISION_CLASSIFICATION_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Supervision classification mismatch")

    if str(request.nonce).strip() != str(claims.get("nonce", "")).strip():
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("token_mismatch_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "NONCE_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Confirmation nonce mismatch")

    if request.correlation_id and str(request.correlation_id).strip() != correlation_id:
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("token_mismatch_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "CORRELATION_ID_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "provided_correlation_id": str(request.correlation_id),
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Correlation id mismatch")

    if request.policy_version and str(request.policy_version).strip() != policy_version:
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("token_mismatch_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "POLICY_VERSION_MISMATCH",
                "intent_id": intent_id,
                "token_id": token_id,
                "provided_policy_version": str(request.policy_version),
                "policy_version": policy_version,
                "correlation_id": correlation_id,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Policy version mismatch")

    consume_result = _redis_consume_confirmation_guards(
        token_id=token_id,
        nonce=str(request.nonce),
        request_hash=request_hash,
        intent_hash=str(request.intent_hash),
        expires_at=int(claims.get("expires_at", now_ts) or now_ts),
    )

    if consume_result == "NONCE_REPLAY_DETECTED":
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("replay_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "NONCE_REPLAY_DETECTED",
                "intent_id": intent_id,
                "nonce": request.nonce,
                "token_id": token_id,
                "request_hash": request_hash,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Confirmation nonce replay detected")

    if consume_result == "DUPLICATE_CONFIRMATION_REQUEST":
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("duplicate_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "DUPLICATE_CONFIRMATION_REQUEST",
                "intent_id": intent_id,
                "request_hash": request_hash,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Duplicate confirmation request detected")

    if consume_result == "INTENT_HASH_REPLAY_DETECTED":
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("replay_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "INTENT_HASH_REPLAY_DETECTED",
                "intent_id": intent_id,
                "request_hash": request_hash,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=409, detail="Intent hash replay detected")

    if consume_result in {"TOKEN_NOT_ISSUED", "TOKEN_ALREADY_USED", "TOKEN_EXPIRED"}:
        _assistant_metric_increment("confirmations_rejected")
        _assistant_metric_increment("replay_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": consume_result,
                "intent_id": intent_id,
                "request_hash": request_hash,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        if consume_result == "TOKEN_EXPIRED":
            raise HTTPException(status_code=401, detail="Confirmation token expired")
        raise HTTPException(status_code=409, detail="Confirmation token already consumed")

    if consume_result != "OK":
        _assistant_metric_increment("confirmations_rejected")
        _append_assistant_ledger_event(
            "confirmation_rejected",
            user,
            {
                "reason": "GUARD_CONSUME_FAILED",
                "consume_result": consume_result,
                "intent_id": intent_id,
                "request_hash": request_hash,
                "token_id": token_id,
                "correlation_id": correlation_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "policy_decision": policy_decision,
                "sensitivity_tier": sensitivity_tier,
                "supervision_classification": supervision_classification,
            },
        )
        raise HTTPException(status_code=503, detail="Distributed replay protection unavailable")

    preview_payload: dict[str, Any]
    try:
        preview_payload = normalize_assistant_preview_payload(
            json.loads(str(preview_record.get("preview_payload_json") or "{}"))
        )
    except Exception:
        preview_payload = normalize_assistant_preview_payload({})

    preview_payload["security_state"] = {
        "verified_preview": True,
        "signed_confirmation": True,
        "token_expires_in_seconds": max(0, int(claims.get("expires_at", now_ts)) - now_ts),
        "dry_run_only": True,
        "execution_disabled": True,
        "supervision_enforced": True,
        "durable_verified_preview": True,
        "audit_chain_active": True,
        "distributed_replay_protection": True,
        "policy_version": policy_version,
        "correlation_id": correlation_id,
    }
    preview_payload["confirmation_verification"] = {
        "status": "VERIFIED_PREVIEW",
        "confirmed_at": now_ts,
        "token_id": token_id,
        "request_hash": request_hash,
        "replay_protection": "distributed_single_use_enforced",
        "policy_version": policy_version,
        "policy_scope": policy_scope,
        "policy_decision": policy_decision,
        "correlation_id": correlation_id,
    }
    preview_payload["governance"] = {
        "durable_verified_preview": True,
        "audit_chain_active": True,
        "distributed_replay_protection": True,
        "policy_version": policy_version,
        "policy_scope": policy_scope,
        "policy_decision": policy_decision,
        "sensitivity_tier": sensitivity_tier,
        "correlation_id": correlation_id,
    }

    _mark_assistant_preview_confirmed(intent_id, now_ts)
    _assistant_metric_increment("confirmations_verified")
    _assistant_metric_increment("confirm_latency_ms_total", (time.perf_counter() - started_at) * 1000.0)
    _assistant_metric_increment("confirm_latency_count", 1.0)

    _append_assistant_ledger_event(
        "confirmation_verified",
        user,
        {
            "intent_id": intent_id,
            "action_type": request.action_type,
            "request_hash": request_hash,
            "token_id": token_id,
            "session_id": request.session_id,
            "correlation_id": correlation_id,
            "policy_version": policy_version,
            "policy_scope": policy_scope,
            "policy_decision": policy_decision,
            "sensitivity_tier": sensitivity_tier,
            "supervision_classification": supervision_classification,
        },
    )

    try:
        workflow_execution = execute_verified_intent(
            user_id=str(user.user_id),
            role=str(user.role),
            intent_id=intent_id,
            action_type=str(request.action_type),
            session_id=str(request.session_id),
            request_hash=request_hash,
            correlation_id=correlation_id,
            policy_version=policy_version,
            policy_scope=policy_scope,
            supervision_classification=supervision_classification,
            preview_payload=preview_payload,
        )
    except Exception as exc:
        log_operational_event(
            user_id=str(user.user_id),
            role=str(user.role),
            event_type="workflow",
            event_name="assistant_execution_hook_failed",
            status="failed",
            session_id=str(request.session_id),
            correlation_id=correlation_id,
            payload={"intent_id": intent_id, "action_type": str(request.action_type)},
            error_message=str(exc),
        )
        workflow_execution = {
            "execution_id": "",
            "intent_id": intent_id,
            "status": "failed",
            "action_type": str(request.action_type),
            "session_id": str(request.session_id),
            "correlation_id": correlation_id,
            "queued_at": None,
            "started_at": None,
            "completed_at": None,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "result": {},
            "error_message": "execution_foundation_unavailable",
            "policy_version": policy_version,
            "policy_scope": policy_scope,
            "supervision_classification": supervision_classification,
        }

    preview_payload["workflow_execution"] = workflow_execution
    preview_payload["execution_pipeline"] = {
        "active": True,
        "foundation_version": "phase_36",
        "states": ["pending", "running", "completed", "failed"],
    }

    log_operational_event(
        user_id=str(user.user_id),
        role=str(user.role),
        event_type="assistant",
        event_name="confirmation_executed",
        status="success",
        session_id=str(request.session_id),
        correlation_id=correlation_id,
        payload={
            "intent_id": intent_id,
            "execution_id": workflow_execution.get("execution_id"),
            "action_type": str(request.action_type),
        },
    )

    return normalize_assistant_preview_payload(preview_payload)



# Serve static files from backend/static/
_static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
    # Keep an assets alias for SPA bundle compatibility.
    app.mount("/assets", StaticFiles(directory=_static_dir), name="assets")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    icon_path = os.path.join(_static_dir, "branding", "favicon.ico")
    if os.path.isfile(icon_path):
        return FileResponse(icon_path, media_type="image/x-icon")
    return Response(status_code=204)


@app.get("/brand-preview", include_in_schema=False)
def brand_preview_gallery() -> HTMLResponse:
    """Branded surface gallery for pre-deployment review."""
    preview_path = os.path.join(_static_dir, "branding", "preview.html")
    with open(preview_path, "r", encoding="utf-8") as f:
        html = f.read()
    response = HTMLResponse(content=html, media_type="text/html")
    response.headers["Cache-Control"] = "no-store"
    return response


def _chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(text):
        chunks.append(text[start:start + chunk_size])
        start += step
    return chunks


def _extract_upload_text(filename: str | None, content_type: str, content: bytes) -> tuple[str | None, dict[str, Any], dict | None]: # type: ignore
    diagnostics: dict[str, Any] = {
        "parser": "none",
        "warnings": [],
    }
    if content_type.startswith("text/") or content_type == "application/json":
        diagnostics["parser"] = "utf8-text"
        return content.decode("utf-8", errors="replace"), diagnostics, None
    if content_type == "application/pdf":
        pypdf = importlib.import_module("pypdf")

        diagnostics["parser"] = "pypdf"
        reader = pypdf.PdfReader(BytesIO(content))
        pages: list[str] = [str(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(filter(None, pages)).strip(), diagnostics, None
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        docx = importlib.import_module("docx")

        diagnostics["parser"] = "python-docx"
        document = docx.Document(BytesIO(content))
        paragraphs: list[str] = [str(paragraph.text) for paragraph in document.paragraphs if str(paragraph.text).strip()]
        return "\n".join(paragraphs).strip(), diagnostics, None
    if content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        diagnostics["parser"] = "openpyxl"
        try:
            openpyxl = importlib.import_module("openpyxl")
            workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
            rows_out: list[str] = []
            for sheet in workbook.worksheets[:4]:
                rows_out.append(f"[Sheet: {sheet.title}]")
                for row in sheet.iter_rows(min_row=1, max_row=40, values_only=True):
                    values = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
                    if values:
                        rows_out.append(" | ".join(values[:12]))
            return "\n".join(rows_out).strip(), diagnostics, None
        except Exception as exc:
            diagnostics["warnings"].append(f"Spreadsheet parse failed: {exc}")
            return None, diagnostics, None
    if content_type in ("image/png", "image/jpeg", "image/webp"):
        diagnostics["parser"] = "image-ocr"
        ocr_result = image_ocr.extract(content_type, content) # type: ignore
        diagnostics["ocr"] = ocr_result["diagnostics"]
        diagnostics["ocr_method"] = ocr_result["method"]
        combined = image_ocr.build_context_block(filename, ocr_result) # type: ignore
        return combined, diagnostics, ocr_result # type: ignore
    diagnostics["warnings"].append(f"No extractor available for {content_type}.")
    return None, diagnostics, None


def _categorize_upload(content_type: str, filename: str | None, extracted_text: str | None) -> str:
    name = (filename or "").lower()
    text = (extracted_text or "").lower()
    if content_type.startswith("image/"):
        return "image"
    if "spreadsheet" in content_type or name.endswith(".xlsx") or name.endswith(".csv"):
        return "spreadsheet"
    if "invoice" in name or "invoice" in text:
        return "invoice"
    if "resume" in name or "curriculum" in text:
        return "resume"
    if "report" in name or "summary" in name:
        return "report"
    if "application/pdf" == content_type:
        return "pdf_document"
    if "wordprocessingml" in content_type:
        return "docx_document"
    return "text_document"


def _summarize_document_text(text: str | None, max_len: int = 420) -> str | None:
    if not text:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    # Extractive lightweight summary for predictable runtime behavior.
    sentences = [s.strip() for s in cleaned.split(".") if s.strip()]
    if not sentences:
        return cleaned[:max_len]
    summary = ". ".join(sentences[:3]).strip()
    if len(summary) > max_len:
        summary = summary[: max_len - 3].rstrip() + "..."
    elif not summary.endswith("."):
        summary += "."
    return summary


# ── Health endpoints ──────────────────────────────────────────────────────────
@app.get("/")
def frontend(request: Request) -> HTMLResponse:
    """Serve main application UI."""
    return _build_app_shell_response(request)


@app.get("/api/health")
def health():
    """Shallow liveness check — returns 200 if the process is alive.
    
    Normalized response format:
      { ok: true, data: {...}, error: null, meta: {...} }
    """
    return responses_module.normalize_success(
        data={
            "status": "ok",
            "version": resolve_app_version(),
        },
        version=resolve_app_version(),
    )


@app.get("/api/health/detail")
def health_detail():
    """Deep readiness check — env validation + live DB probe.
    
    Normalized response format:
      { ok: true/false, data: {...}, error: null, meta: {...} }
    """
    report   = app_startup.startup_report() # type: ignore
    db_check = app_startup.validate_database() # type: ignore
    all_ok   = report.get("ok", False) and db_check["ok"] # type: ignore

    try:
        from app.monitoring.runtime_logger import record_supervision_event
        if not all_ok:
            record_supervision_event(
                subsystem="health",
                event="detail_probe_failed",
                details={
                    "startup_ok": bool(report.get("ok", False)),
                    "db_ok": bool(db_check.get("ok", False)),
                    "db_error": db_check.get("error"),
                },
            )
    except Exception:
        pass
    
    status_code = 200 if all_ok else 503
    response_data = { # type: ignore
        "status": "healthy" if all_ok else "degraded",
        "db": db_check,
        "startup": report,
        "version": resolve_app_version(),
    }
    
    if all_ok:
        response = responses_module.normalize_success(
            data=response_data,
            version=resolve_app_version(),
        )
    else:
        response = responses_module.normalize_error(
            error_msg="System degraded: health check failed",
            latency_ms=0,
        )
        response.data = response_data  # Include diagnostic data even on error
    
    return JSONResponse(
        status_code=status_code,
        content=responses_module.as_dict(response),
    )


# ── App shell ─────────────────────────────────────────────────────────────────
@app.get("/app")
def serve_app(request: Request) -> HTMLResponse:
    """Serve main platform UI (Nova operational shell)."""
    return _build_ops_shell_response(request)


@app.get("/app/dashboard")
@app.get("/app/rides")
@app.get("/app/providers")
@app.get("/app/drivers")
@app.get("/app/operations")
@app.get("/app/operations/live")
@app.get("/app/operations/federation")
@app.get("/app/operations/replay")
@app.get("/app/operations/predictive")
@app.get("/app/operations/governance")
@app.get("/app/operations/command-center")
@app.get("/app/operations/timeline")
@app.get("/app/operations/map-preview")
@app.get("/app/operations/alerts")
@app.get("/app/system-health")
@app.get("/app/ai-assistant")
def serve_ops_shell(request: Request) -> HTMLResponse:
    """Serve Phase 8 operational shell routes with a shared frontend payload."""
    return _build_ops_shell_response(request)


@app.get("/dashboard", include_in_schema=False)
@app.get("/rides", include_in_schema=False)
@app.get("/mobile", include_in_schema=False)
@app.get("/providers", include_in_schema=False)
@app.get("/drivers", include_in_schema=False)
@app.get("/operations", include_in_schema=False)
@app.get("/operations/live", include_in_schema=False)
@app.get("/operations/federation", include_in_schema=False)
@app.get("/operations/replay", include_in_schema=False)
@app.get("/operations/predictive", include_in_schema=False)
@app.get("/operations/governance", include_in_schema=False)
@app.get("/operations/command-center", include_in_schema=False)
@app.get("/operations/timeline", include_in_schema=False)
@app.get("/operations/map-preview", include_in_schema=False)
@app.get("/operations/alerts", include_in_schema=False)
@app.get("/system-health", include_in_schema=False)
@app.get("/ai-assistant", include_in_schema=False)
def redirect_legacy_ops_aliases(request: Request) -> RedirectResponse:
    """Redirect legacy root-level shell aliases to canonical /app/* paths."""
    return RedirectResponse(url=f"/app{request.url.path}", status_code=307)


@app.get("/app/{full_path:path}", include_in_schema=False)
def app_spa_fallback(full_path: str, request: Request) -> HTMLResponse:
    """Fallback for deep links under /app when the path is client-routed."""
    return _build_ops_shell_response(request)


def _build_app_shell_response(request: Request | None = None) -> HTMLResponse:
    """Serve app shell with runtime contract injected and cache disabled."""
    index = os.path.join(_static_dir, "index.html")
    with open(index, "r", encoding="utf-8") as f:
        html = f.read()
    html = inject_runtime_contract(html, request=request)
    response = HTMLResponse(content=html, media_type="text/html")
    response.headers["X-Amicor-Frontend-Build"] = FRONTEND_BUILD_VERSION
    response.headers["X-Amicor-Hydration-Version"] = HYDRATION_VERSION
    response.headers["X-Amicor-Build-Version"] = FRONTEND_BUILD_VERSION
    response.headers["X-Amicor-Runtime-Environment"] = RUNTIME_ENVIRONMENT
    response.headers["Cache-Control"] = "no-store"
    return response


def _build_ops_shell_response(request: Request | None = None) -> HTMLResponse:
    """Serve Phase 8 operations shell with runtime contract injection and no cache."""
    shell_path = os.path.join(_static_dir, "ops-shell.html")
    with open(shell_path, "r", encoding="utf-8") as f:
        html = f.read()
    html = inject_runtime_contract(html, request=request)
    response = HTMLResponse(content=html, media_type="text/html")
    response.headers["X-Amicor-Frontend-Build"] = FRONTEND_BUILD_VERSION
    response.headers["X-Amicor-Hydration-Version"] = HYDRATION_VERSION
    response.headers["X-Amicor-Build-Version"] = FRONTEND_BUILD_VERSION
    response.headers["X-Amicor-Runtime-Environment"] = RUNTIME_ENVIRONMENT
    response.headers["Cache-Control"] = "no-store"
    return response


# ── Chat ──────────────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(request: ChatRequest) -> responses_module.NormalizedResponse:
    """Process a chat message and return AI response.
    
    Normalized response format:
      { ok: true, data: {...}, error: null, meta: {...} }
    
    Data includes: reply, tool, sources, status, capability, meta
    
    Args:
        request: Chat request with validated user_id and message
        
    Returns:
        Normalized success response with chat reply
        
    Raises:
        HTTPException 422 if validation fails
    """
    logger.debug("Chat from user=%s: %r", request.user_id, request.message[:80])
    try:
        result: dict[str, Any] = route_message(request.message, user_id=request.user_id)  # type: ignore
        # Sanitize meta to remove internal provider diagnostics from user-facing response
        user_meta = _sanitize_tool_meta(result.get("meta", {})) # type: ignore
        response_data = { # type: ignore
            "reply": result["response"],
            "tool": result.get("tool", "openai"),
            "sources": result.get("sources", []),
            "status": result.get("status", "success"),
            "capability": result.get("capability", {}),
            "meta": user_meta,
        }
        return responses_module.normalize_success(
            data=response_data,
        )
    except Exception as exc:
        logger.exception("Router error for user=%s", request.user_id)
        error_response = responses_module.normalize_error(
            error_msg=f"Chat processing failed: {str(exc)}"
        )
        return JSONResponse(
            status_code=500,
            content=responses_module.as_dict(error_response),
        ) # type: ignore


@app.get("/api/history/{user_id}")
def history(user_id: str, limit: int = 50) -> dict[str, Any]:
    """Retrieve chat history and memory for user.
    
    Args:
        user_id: User identifier (validated)
        limit: Max messages to retrieve (1-100)
        
    Returns:
        Dict with user_id, messages, and memory summary
    """
    validated_user_id = validation_module.validate_user_id(user_id)
    validated_limit = max(1, min(int(limit), 100))
    
    return {
        "user_id": validated_user_id,
        "messages": get_chat_history(validated_user_id, limit=validated_limit),
        "memory": {
            "summary": get_memory_summary(validated_user_id),
            "preferences": get_preferences(validated_user_id),
        },
    }


# ── Memory reset ──────────────────────────────────────────────────────────────
@app.post("/api/reset")
def reset_chat(req: ResetRequest) -> dict[str, bool]:
    """Clear user memory and reset conversation state.
    
    Args:
        req: Reset request with validated user_id
        
    Returns:
        Dict confirming reset status
        
    Raises:
        HTTPException 422 if validation fails
        HTTPException 500 if reset fails
    """
    user_id = req.user_id
    try:
        clear_user_memory(user_id)
        logging_utils.log_event(
            logger,
            logging.INFO,
            event="memory.reset.success",
            message="Memory reset completed",
            route="/api/reset",
            user_id=user_id,
            status="ok",
        )
        return {"success": True}
    except Exception as exc: # type: ignore
        logger.exception("Reset error for user=%s", user_id)
        logging_utils.log_event(
            logger,
            logging.ERROR,
            event="memory.reset.error",
            message="Memory reset failed",
            route="/api/reset",
            user_id=user_id,
            error=logging_utils.safe_exception_message(exc),
            status="error",
        )
        raise HTTPException(status_code=500, detail="Reset failed")


# ── File upload ───────────────────────────────────────────────────────────────
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:  # type: ignore
    """Accept a user-uploaded document for context injection.

    - Max 10 MB.
    - Allowed: text/*, application/json, application/pdf, image/png, jpeg, webp.
    - Returns extracted UTF-8 text for text-type files (first 8 000 chars).
    
    Args:
        file: Uploaded file with validated content type and size
        
    Returns:
        Dict with extracted text, diagnostics, and metadata
        
    Raises:
        HTTPException 415 if unsupported content type
        HTTPException 413 if file too large
        HTTPException 400 if parse error
    """
    content = await file.read(MAX_UPLOAD_BYTES + 1)

    try:
        filename = validation_module.validate_filename(file.filename)
        content_type = (file.content_type or "application/octet-stream").split(";")[0].strip()
        validation_module.validate_content_type(content_type, ALLOWED_UPLOAD_TYPES) # type: ignore
        validation_module.validate_extension_mime_policy(content_type, filename)
        validation_module.validate_file_size(len(content), MAX_UPLOAD_BYTES, filename)
        validation_module.validate_file_signature(content_type, content, filename)
        validation_module.validate_archive_safety(content_type, content, filename)
    except HTTPException as exc:
        observability.increment("uploads.rejected")
        logging_utils.log_event(
            logger,
            logging.WARNING,
            event="upload.rejected.validation",
            message="Upload rejected by validation",
            filename=file.filename,
            content_type=(file.content_type or "application/octet-stream"),
            size_bytes=len(content),
            status_code=exc.status_code,
            error=str(exc.detail),
        )
        raise

    try:
        extracted_text, diagnostics, ocr_result = _extract_upload_text(filename, content_type, content) # type: ignore
    except (BadZipFile, ValueError) as exc:
        observability.increment("uploads.rejected")
        logging_utils.log_event(
            logger,
            logging.WARNING,
            event="upload.rejected.parse",
            message="Upload rejected due to parse error",
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            error=logging_utils.safe_exception_message(exc),
        )
        raise HTTPException(status_code=400, detail=f"Could not parse upload: {exc}")
    except Exception as exc:
        observability.increment("uploads.errors")
        logging_utils.log_event(
            logger,
            logging.ERROR,
            event="upload.error.parse",
            message="Upload parse error",
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            error=logging_utils.safe_exception_message(exc),
        )
        raise HTTPException(status_code=500, detail=f"Upload parsing failed: {exc}")

    truncated_text = extracted_text[:8000] if extracted_text else None
    chunks = _chunk_text(extracted_text or "")

    logging_utils.log_event(
        logger,
        logging.INFO,
        event="upload.accepted",
        message="Upload accepted",
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
    )

    response_payload: dict[str, Any] = {
        "filename":       filename,
        "content_type":   content_type,
        "size_bytes":     len(content),
        "extracted_text": truncated_text,
        "upload_category": _categorize_upload(content_type, file.filename, extracted_text),
        "document_summary": _summarize_document_text(extracted_text),
        "chunk_count":    len(chunks),
        "chunks":         chunks[:8],
        "diagnostics":    {
            **diagnostics,
            "text_length": len(extracted_text or ""),
            "truncated": bool(extracted_text and len(extracted_text) > 8000),
        },
        "status": "uploaded",
    }

    # Attach OCR-specific fields for images
    if ocr_result:
        response_payload["ocr"] = {
            "method":      ocr_result["method"],
            "confidence":  ocr_result["confidence"],
            "word_count":  ocr_result["word_count"],
            "description": ocr_result.get("description"), # type: ignore
            "has_text":    bool(ocr_result.get("text")), # type: ignore
        }

    # Record upload metrics and persist to platform_uploads
    ocr_result_ref = response_payload.get("ocr")
    log_upload(
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        ocr_method=(ocr_result_ref or {}).get("method") if ocr_result_ref else None, # type: ignore
        ocr_confidence=(ocr_result_ref or {}).get("confidence") if ocr_result_ref else None, # type: ignore
        ocr_word_count=(ocr_result_ref or {}).get("word_count") if ocr_result_ref else None, # type: ignore
    )
    observability.increment("uploads.total")
    if content_type.startswith("image/"):
        observability.increment("uploads.images")

    return response_payload  # type: ignore


# ── Streaming chat ────────────────────────────────────────────────────────────
async def _stream_openai(message: str, user_id: str) -> AsyncIterator[str]:
    """Yield Server-Sent Event chunks for OpenAI streaming responses."""
    import os as _os
    from app.database import (  # type: ignore
        get_memory_summary, get_preferences, get_recent_messages, # type: ignore
        save_message, save_memory_summary,
    )
    from app.router import _memory_context, _extract_preferences, _summarize_history, _build_memory_capability_response, _enforce_memory_identity_response  # type: ignore

    openai_mod = importlib.import_module("openai")
    api_key = _os.getenv("OPENAI_API_KEY")
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'content': 'OpenAI not configured.'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    client = openai_mod.OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SECONDS)
    memory_summary = get_memory_summary(user_id)
    memory_preferences = cast(dict[str, str], get_preferences(user_id))
    has_memory = (
        bool(memory_summary and str(memory_summary).strip())
        or (len(memory_preferences) > 0)
    )
    history = _memory_context(user_id) + get_recent_messages(user_id, limit=10) # type: ignore
    history.append({"role": "user", "content": message}) # type: ignore

    # Save user message before streaming
    save_message(user_id, "user", message)
    prefs = _extract_preferences(message) # type: ignore
    from app.database import save_preference  # type: ignore
    for k, v in prefs.items(): # type: ignore
        save_preference(user_id, k, v) # type: ignore

    memory_capability_response = _build_memory_capability_response(message, user_id) # type: ignore
    if memory_capability_response:
        save_message(user_id, "assistant", memory_capability_response)
        recent = get_recent_messages(user_id, limit=12) # type: ignore
        summary = _summarize_history(recent)
        if summary:
            save_memory_summary(user_id, summary)
        yield f"data: {json.dumps({'type': 'token', 'content': memory_capability_response})}\n\n"
        yield "data: [DONE]\n\n"
        return

    full_response = []
    provider_t0 = asyncio.get_running_loop().time()
    logging_utils.log_request_lifecycle(
        logger,
        logging.INFO,
        event="REQUEST_PROVIDER_BEGIN",
        route="/api/chat/stream",
        provider="openai",
        status="begin",
    )
    try:
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=history,
            stream=True,
            max_tokens=1024,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                token = delta.content
                full_response.append(token) # type: ignore
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                await asyncio.sleep(0)  # yield to event loop
    except Exception as exc:
        logger.exception("Streaming error for user=%s", user_id)
        latency_ms = int((asyncio.get_running_loop().time() - provider_t0) * 1000)
        err_msg = logging_utils.safe_exception_message(exc)
        if "timed out" in err_msg.lower() or isinstance(exc, TimeoutError):
            logging_utils.log_request_lifecycle(
                logger,
                logging.ERROR,
                event="REQUEST_TIMEOUT",
                route="/api/chat/stream",
                latency_ms=latency_ms,
                provider="openai",
                status="timeout",
                error=err_msg,
            )
        logging_utils.log_request_lifecycle(
            logger,
            logging.ERROR,
            event="REQUEST_PROVIDER_FAIL",
            route="/api/chat/stream",
            latency_ms=latency_ms,
            provider="openai",
            status="failed",
            error=err_msg,
        )
        yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

    # Save completed response and update summary
    if full_response:
        logging_utils.log_request_lifecycle(
            logger,
            logging.INFO,
            event="REQUEST_PROVIDER_SUCCESS",
            route="/api/chat/stream",
            latency_ms=int((asyncio.get_running_loop().time() - provider_t0) * 1000),
            provider="openai",
            status="ok",
        )
        assembled = "".join(full_response) # type: ignore
        assembled = _enforce_memory_identity_response(assembled, has_memory=has_memory, memory_enabled=True) # type: ignore
        save_message(user_id, "assistant", assembled)
        recent = get_recent_messages(user_id, limit=12) # type: ignore
        summary = _summarize_history(recent)
        if summary:
            save_memory_summary(user_id, summary)

    yield "data: [DONE]\n\n"


def _sanitize_tool_meta(meta: dict) -> dict: # type: ignore
    """Remove internal provider diagnostics from user-facing response.
    
    Keeps only metadata relevant to user experience.
    Filters out: provider_errors, provider_latency_ms, circuit_breaker_state, etc.
    """
    if not isinstance(meta, dict): # type: ignore
        return {}
    
    # Whitelist safe metadata fields
    safe_meta = {}
    for key in [
        "query",
        "provider",
        "result_count",
        "cache_hit",
        "search_available",
        "tool_executed",
        "tool_id",
        "tool_card",
        "browser_actions",
        "workflow_steps",
    ]:
        if key in meta:
            safe_meta[key] = meta[key]
    
    return safe_meta # type: ignore


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:  # type: ignore
    """
    Streaming variant of /api/chat.
    Returns text/event-stream with SSE chunks:
      data: {"type": "token", "content": "..."}\n\n
      data: [DONE]\n\n
    Falls back to non-streaming for tool calls (weather, search, etc.)
    """
    lower = request.message.lower()
    from app.router import CAPABILITIES  # type: ignore

    # Check if a tool capability matches — if so, use standard route and emit as single event
    for name, cap in CAPABILITIES.items(): # type: ignore
        if any(t in lower for t in cap["triggers"]): # type: ignore
            try:
                result = route_message(request.message, user_id=request.user_id) # type: ignore
                # Sanitize meta to remove internal diagnostics
                user_meta = _sanitize_tool_meta(result.get("meta", {})) # type: ignore
                payload = json.dumps({
                    "type":       "complete",
                    "reply":      result["response"],
                    "tool":       result.get("tool", name), # type: ignore
                    "sources":    result.get("sources", []), # type: ignore
                    "status":     result.get("status", "success"), # type: ignore
                    "capability": result.get("capability", {}), # type: ignore
                    "meta":       user_meta,
                })
                async def _tool_stream():  # type: ignore
                    yield f"data: {payload}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(_tool_stream(), media_type="text/event-stream")
            except Exception as exc:
                logger.exception("Tool stream error for user=%s", request.user_id)
                raise HTTPException(status_code=500, detail=str(exc))

    # OpenAI streaming
    return StreamingResponse(
        _stream_openai(request.message, request.user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Provider resilience diagnostics ──────────────────────────────────────────

@app.get("/api/diagnostics/providers")
def provider_diagnostics() -> responses_module.NormalizedResponse:  # type: ignore
    """Return health and circuit-breaker state for all providers.
    
    Normalized response format:
      { ok: true, data: {...}, error: null, meta: {...} }
    
    Returns:
        Normalized response with provider diagnostics
    """
    try:
        from app.providers.resilience import all_diagnostics  # type: ignore
        providers_data = all_diagnostics() # type: ignore
        return responses_module.normalize_success(
            data={
                "providers": providers_data,
                "version": resolve_app_version(),
            },
            version=resolve_app_version(),
        )
    except Exception as exc:
        logger.exception("Provider diagnostics error")
        return JSONResponse(
            status_code=500,
            content=responses_module.as_dict(
                responses_module.normalize_error(
                    error_msg=f"Failed to retrieve provider diagnostics: {str(exc)}"
                )
            ),
        ) # type: ignore


# ── Admin dashboard ───────────────────────────────────────────────────────────

@app.get("/api/admin/dashboard")
def admin_dashboard() -> dict[str, Any]:  # type: ignore
    """Aggregated platform status: DB health, provider states, session counters,
    upload stats, observability metrics.
    Not auth-protected in dev mode; add require_auth in production.
    
    Returns:
        Dict with comprehensive platform status
    """
    from app.providers.resilience import all_diagnostics  # type: ignore
    from app.db.session import check_db_connection        # type: ignore

    db_ok = check_db_connection()

    # Count registered users and recent uploads from platform tables
    user_count   = 0
    upload_count = 0
    recent_logs: list = [] # type: ignore
    try:
        from app.db.session import SessionLocal   # type: ignore
        from app.db.models import User, Upload, ProviderLog  # type: ignore
        db = SessionLocal()
        try:
            user_count   = db.query(User).count()
            upload_count = db.query(Upload).count()
            recent_logs  = [ # type: ignore
                {
                    "provider": r.provider_name,
                    "success":  r.success,
                    "latency_ms": r.latency_ms,
                    "error_msg":  r.error_msg,
                    "created_at": r.created_at.isoformat(),
                }
                for r in db.query(ProviderLog)
                          .order_by(ProviderLog.id.desc())
                          .limit(20)
                          .all()
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Admin dashboard DB query failed: %s", exc)

    return {
        "status": "ok",
        "database": {
            "reachable": db_ok,
        },
        "platform": {
            "registered_users": user_count,
            "total_uploads":    upload_count,
        },
        "providers": all_diagnostics(),
        "observability": observability.get_metrics(),
        "recent_provider_logs": recent_logs,
        "version": resolve_app_version(),
    } # type: ignore


@app.get("/api/admin/metrics")
def admin_metrics() -> dict[str, Any]:
    """Lightweight metrics endpoint — counters, latencies, recent errors.
    
    Returns:
        Dict with observability metrics
    """
    return observability.get_metrics()


# ── Admin UI (serves static admin.html) ───────────────────────────────────────

@app.get("/admin")
def serve_admin() -> Response:
    """Serve admin dashboard UI.
    
    Returns:
        Admin HTML page or 404 error
    """
    admin_html = os.path.join(_static_dir, "admin.html")
    if os.path.isfile(admin_html):
        return FileResponse(admin_html, media_type="text/html")
    return JSONResponse({"error": "Admin UI not found"}, status_code=404)


@app.get("/platform-ops/driver-apply")
def serve_driver_onboarding_apply() -> Response:
    page = os.path.join(_static_dir, "platform-ops", "driver-apply.html")
    if os.path.isfile(page):
        return FileResponse(page, media_type="text/html")
    return JSONResponse({"error": "Driver application page not found"}, status_code=404)


@app.get("/platform-ops/driver-onboarding-admin")
def serve_driver_onboarding_admin() -> Response:
    page = os.path.join(_static_dir, "platform-ops", "driver-onboarding-admin.html")
    if os.path.isfile(page):
        return FileResponse(page, media_type="text/html")
    return JSONResponse({"error": "Driver onboarding admin page not found"}, status_code=404)


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str, request: Request) -> Response:
    """Global SPA fallback registered last to preserve /api and asset route priority."""
    normalized = (full_path or "").lstrip("/")
    if (
        normalized.startswith("api/")
        or normalized.startswith("static/")
        or normalized.startswith("assets/")
        or normalized == "favicon.ico"
    ):
        raise HTTPException(status_code=404, detail="Not Found")

    # Unknown file-like paths should stay 404 instead of rendering SPA HTML.
    if "." in normalized.rsplit("/", 1)[-1]:
        raise HTTPException(status_code=404, detail="Not Found")

    return _build_app_shell_response(request)
