"""startup.py — Production startup validation and graceful shutdown for Amicor.

Responsibilities:
  - Validate required environment variables before accepting traffic.
  - Verify database connectivity independently of the ORM layer.
  - Register SIGTERM / SIGINT handlers for graceful shutdown.
  - Expose startup_report() so the /api/health/detail endpoint can surface it.
  - Provide startup_recovery() that retries DB validation on transient failures.
"""

import os
import signal
import sqlite3
import logging
import time
from typing import Optional

logger = logging.getLogger("amicor.startup")

_DEFAULT_DB = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "chat.db")
)

# ── Required / optional env-var declarations ───────────────────────────────────
REQUIRED_VARS: list[str] = [
    "OPENAI_API_KEY",
]

OPTIONAL_VARS: dict[str, str] = {
    "ALLOWED_ORIGINS":  "Defaults to * — unsafe for production, set to your domain.",
    "LOG_LEVEL":        "Defaults to INFO.",
    "DB_FILENAME":      f"Defaults to {_DEFAULT_DB}.",
    "MAX_HISTORY":      "Defaults to 10 messages.",
    "APP_VERSION":      "Defaults to 'dev'.",
    "AMICOR_BUILD_VERSION": "Canonical runtime version used by frontend build and hydration contract.",
    "AMICOR_FRONTEND_BUILD_VERSION": "Legacy/deprecated split version variable (ignored by runtime contract).",
    "AMICOR_HYDRATION_VERSION": "Legacy/deprecated split version variable (ignored by runtime contract).",
}

# ── Runtime state ─────────────────────────────────────────────────────────────
_startup_report: dict = {} # type: ignore
_shutdown_requested: bool = False


def is_shutdown_requested() -> bool:
    """Return True if a SIGTERM/SIGINT has been received."""
    return _shutdown_requested


def _handle_shutdown(signum: int, frame) -> None: # type: ignore
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown signal received (signal %s) — draining requests…", signum)


def register_shutdown_handlers() -> None:
    """Register SIGTERM and SIGINT handlers for graceful shutdown."""
    signal.signal(signal.SIGTERM, _handle_shutdown) # type: ignore
    signal.signal(signal.SIGINT,  _handle_shutdown) # type: ignore
    logger.info("Shutdown handlers registered (SIGTERM, SIGINT).")


# ── Environment validation ─────────────────────────────────────────────────────
def validate_environment() -> dict: # type: ignore
    """Check required and optional env vars. Returns a status dict."""
    missing  = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    warnings = []
    for var, note in OPTIONAL_VARS.items():
        if not os.environ.get(var):
            warnings.append(f"{var} not set — {note}") # type: ignore
    return {
        "ok":               len(missing) == 0,
        "missing_required": missing,
        "warnings":         warnings,
    } # type: ignore


# ── Database validation ────────────────────────────────────────────────────────
def validate_database(db_path: Optional[str] = None) -> dict: # type: ignore
    """Validate the configured runtime database (PostgreSQL or SQLite)."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url.startswith("postgres"):
        try:
            from app.db.session import check_db_connection

            ok = check_db_connection()
            return {
                "ok": ok,
                "backend": "postgresql",
                "database_url_configured": True,
                "detail": "PostgreSQL reachable" if ok else "PostgreSQL unreachable",
            }
        except Exception as exc:
            return {
                "ok": False,
                "backend": "postgresql",
                "database_url_configured": True,
                "error": str(exc),
                "detail": "PostgreSQL connectivity check failed",
            }

    if db_path is None:
        db_path = os.environ.get("DB_FILENAME", _DEFAULT_DB)

    try:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("SELECT 1")
        conn.execute("PRAGMA integrity_check")
        conn.close()
        return {"ok": True, "backend": "sqlite", "db_path": db_path}
    except Exception as exc:
        return {"ok": False, "backend": "sqlite", "db_path": db_path, "error": str(exc)}


def startup_recovery(max_retries: int = 3, delay_s: float = 1.0) -> bool:
    """Retry database validation up to max_retries times.

    Returns True on first success, False if all attempts fail.
    """
    for attempt in range(1, max_retries + 1):
        result = validate_database() # type: ignore
        if result["ok"]:
            logger.info("Database ready (attempt %d/%d).", attempt, max_retries)
            return True
        logger.warning(
            "Database not ready (attempt %d/%d): %s",
            attempt, max_retries, result.get("error"), # type: ignore
        )
        if attempt < max_retries:
            time.sleep(delay_s)
    logger.error("Database unavailable after %d attempts.", max_retries)
    return False


# ── Full startup validation ────────────────────────────────────────────────────
def run_startup_validation() -> dict: # type: ignore
    """Run full startup validation and cache the report globally.

    Always returns the report dict — callers decide whether to abort on failure.
    """
    global _startup_report

    env_result = validate_environment() # type: ignore
    db_result  = validate_database() # type: ignore

    report: dict = { # type: ignore
        "timestamp":   time.time(),
        "environment": env_result,
        "database":    db_result,
        "ok":          env_result["ok"] and db_result["ok"],
        "version":     os.environ.get("APP_VERSION", "dev"),
        "log_level":   os.environ.get("LOG_LEVEL", "INFO"),
    }

    # Log issues
    if env_result["missing_required"]:
        logger.error(
            "Startup validation — missing required env vars: %s",
            env_result["missing_required"], # type: ignore
        )
    for warning in env_result.get("warnings", []): # type: ignore
        logger.warning("Startup warning: %s", warning) # type: ignore
    if not db_result["ok"]:
        logger.error("Startup validation — database error: %s", db_result.get("error")) # type: ignore

    if report["ok"]:
        logger.info(
            "Startup validation passed. version=%s log_level=%s",
            report["version"], report["log_level"], # type: ignore
        )

    _startup_report = report # type: ignore
    return report # type: ignore


def startup_report() -> dict: # type: ignore
    """Return the cached startup report (set by run_startup_validation)."""
    return dict(_startup_report) # type: ignore
