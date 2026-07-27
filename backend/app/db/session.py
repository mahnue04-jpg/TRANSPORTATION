"""
Database session factory.

Supports SQLite (default/development) and PostgreSQL (production).
Set DATABASE_URL env var:
  postgresql://user:pass@host:5432/amicor   — production PostgreSQL
  sqlite:///absolute/path/to/chat.db         — SQLite (derived from DB_FILENAME if not set)
"""
import os

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ── Connection string resolution ───────────────────────────────────────────────
_db_filename = os.getenv("DB_FILENAME", os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "chat.db")
))
_default_url = f"sqlite:///{_db_filename}"
DATABASE_URL: str = os.getenv("DATABASE_URL", _default_url)

_is_sqlite = DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

# Keep SQLite usable under concurrent API polling by allowing a sufficient shared pool.
# SQLite WAL mode supports concurrent reads; use 20 overflow to handle 27+ parallel refresh calls.
_default_pool_size = "5" if _is_sqlite else "10"
_default_max_overflow = "20" if _is_sqlite else "20"
_pool_size = int(os.getenv("DB_POOL_SIZE", _default_pool_size))
_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", _default_max_overflow))

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    echo=os.getenv("DB_ECHO", "0") == "1",
)

# WAL mode + foreign keys for SQLite
if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_platform_db() -> None:
    """Create all SQLAlchemy-managed tables (idempotent, safe to run on startup)."""
    from app.db import models  # noqa: F401 — registers models with Base.metadata
    os.makedirs(os.path.dirname(_db_filename), exist_ok=True)
    Base.metadata.create_all(bind=engine)


def _classify_db_connection_error(exc: Exception) -> str:
    """Map a connection exception to a production-safe blocker category."""
    message = str(exc).lower()
    if "password authentication failed" in message or "authentication failed" in message:
        return "expired_password_or_credentials"
    if "ssl" in message or "certificate" in message:
        return "ssl_connectivity_failure"
    if "could not translate host name" in message or "name or service not known" in message:
        return "incorrect_database_url"
    if "connection refused" in message or "no route to host" in message:
        return "missing_or_suspended_postgresql_service"
    if "timeout" in message or "timed out" in message:
        return "connectivity_failure"
    if "too many clients" in message or "pool" in message:
        return "database_connection_pool_failure"
    if "does not exist" in message and "database" in message:
        return "incorrect_database_url"
    return "connectivity_failure"


def check_db_connection_detail() -> dict:
    """Return connection status with a sanitized error category (no credentials)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"connected": True}
    except Exception as exc:
        return {
            "connected": False,
            "error_class": type(exc).__name__,
            "blocker_category": _classify_db_connection_error(exc),
            "detail": "Database unreachable",
        }


def check_db_connection() -> bool:
    """Return True if the database is reachable."""
    return bool(check_db_connection_detail().get("connected"))
