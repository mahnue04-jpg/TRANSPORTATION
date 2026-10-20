"""
Database session factory.

Supports SQLite (default/development) and PostgreSQL (production).
Set DATABASE_URL env var:
  postgresql://user:pass@host:5432/amicor   — production PostgreSQL
  sqlite:///absolute/path/to/chat.db         — SQLite (derived from DB_FILENAME if not set)
"""
import logging
import os
import uuid

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger("amicor.db.session")

_AUTH_RESTART_MARKER = "amicor_auth_restart_marker"
_PROCESS_BOOT_ID = ""
_postgres_marker_checked = False

# ── Connection string resolution ───────────────────────────────────────────────
def _workspace_sqlite_path() -> str:
    return os.getenv(
        "DB_FILENAME",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "chat.db")),
    )


def _disk_root() -> str:
    """Mounted disk root. Tests can point this at a missing path."""
    configured = os.getenv("AMICOR_AUTH_DISK_DIR", "").strip()
    return configured or "/data/onboarding_docs"


def _candidate_durable_dirs() -> list[tuple[str, str]]:
    """Directories that can keep accounts across a stage process restart."""
    found: list[tuple[str, str]] = []
    explicit = os.getenv("AMICOR_AUTH_STORE_DIR", "").strip()
    if explicit:
        found.append((os.path.abspath(explicit), "configured-directory"))
    disk = _disk_root()
    if os.path.isdir(disk):
        found.append((os.path.abspath(os.path.join(disk, "casting-preview-auth")), "render-disk"))
    return found


def _prepare_private_dir(path: str) -> bool:
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
        probe = os.path.join(path, ".write_probe")
        fd = os.open(probe, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            os.unlink(probe)
        except OSError:
            pass
        return True
    except OSError:
        return False


def _observe_restart_marker(directory: str) -> bool:
    """True when an earlier process already created the marker beside the store.

    The marker contains no password and no signing key. An ephemeral workspace
    never writes one, so a free-tier restart cannot look proven.
    """
    marker = os.path.join(directory, ".restart_marker")
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return True
    except OSError:
        return False
    try:
        os.write(fd, b"1")
    finally:
        os.close(fd)
    try:
        os.chmod(marker, 0o600)
    except OSError:
        pass
    return False


def _postgres_url(url: str) -> bool:
    lowered = url.lower()
    return lowered.startswith("postgres://") or lowered.startswith("postgresql")


def _resolve_sqlite_fallback() -> tuple[str, bool, str, bool]:
    for directory, label in _candidate_durable_dirs():
        if _prepare_private_dir(directory):
            return os.path.join(directory, "chat.db"), True, label, _observe_restart_marker(directory)
    return _workspace_sqlite_path(), False, "workspace", False


_configured_database_url = os.getenv("DATABASE_URL", "").strip()
_auth_restart_observed = False
if _configured_database_url:
    DATABASE_URL = _configured_database_url
    if _postgres_url(DATABASE_URL):
        # Durable, but this process has not seen an earlier instance yet.
        # The marker row is written later, on the seed-status read, not at import.
        _auth_store_durable = True
        _auth_store_location = "postgres"
    else:
        _auth_store_durable = False
        _auth_store_location = "workspace"
else:
    _sqlite_path, _auth_store_durable, _auth_store_location, _auth_restart_observed = _resolve_sqlite_fallback()
    DATABASE_URL = f"sqlite:///{_sqlite_path}"

# The production image installs psycopg2-binary. Some managed PostgreSQL
# connection strings explicitly request SQLAlchemy's psycopg v3 dialect
# (postgresql+psycopg://), which would require a different DBAPI package and
# causes startup to fail with ModuleNotFoundError: psycopg. Normalize that
# driver hint to the installed psycopg2 driver without changing credentials,
# host, database name, or any other connection-string component.
if DATABASE_URL.startswith("postgresql+psycopg://"):
    DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len("postgresql+psycopg://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len("postgresql://"):]

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


def auth_store_metadata() -> dict[str, str | bool]:
    """Safe description of where accounts live. No paths, passwords, or keys."""
    return {
        "backend": "sqlite" if _is_sqlite else "postgres",
        "durable": bool(_auth_store_durable),
        "location": _auth_store_location,
        "restart_observed": bool(_auth_restart_observed),
    }


def current_auth_boot_id() -> str:
    """Identity of this process. Empty values never count as a prior boot."""
    global _PROCESS_BOOT_ID
    for name in ("RENDER_INSTANCE_ID", "AMICOR_AUTH_BOOT_ID"):
        value = os.getenv(name, "").strip()
        if value and len(value) <= 128:
            return value
    if not _PROCESS_BOOT_ID:
        _PROCESS_BOOT_ID = uuid.uuid4().hex
    return _PROCESS_BOOT_ID


def apply_auth_restart_marker(bind, boot_id: str) -> bool:
    """Write this boot id and report whether a different one was already stored.

    The first writer leaves the gate closed. The same id, including an idle
    wake of this process, also stays closed. A later non-empty id is the proof.
    The row holds no password, token, or connection string.
    """
    boot_id = (boot_id or "").strip()
    if not boot_id or len(boot_id) > 128:
        return False
    with bind.connect() as connection:
        connection.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_AUTH_RESTART_MARKER} ("
            "id INTEGER PRIMARY KEY, "
            "instance_id TEXT NOT NULL, "
            "marker_kind TEXT NOT NULL)"
        ))
        connection.commit()
        return _record_boot_marker(connection, boot_id)


def _record_boot_marker(connection, boot_id: str) -> bool:
    row = connection.execute(text(
        f"SELECT instance_id, marker_kind FROM {_AUTH_RESTART_MARKER} WHERE id = 1"
    )).first()
    if row is None:
        try:
            connection.execute(
                text(
                    f"INSERT INTO {_AUTH_RESTART_MARKER} "
                    "(id, instance_id, marker_kind) VALUES (1, :boot, 'instance')"
                ),
                {"boot": boot_id},
            )
            connection.commit()
            return False
        except IntegrityError:
            connection.rollback()
            row = connection.execute(text(
                f"SELECT instance_id, marker_kind FROM {_AUTH_RESTART_MARKER} WHERE id = 1"
            )).first()
            if row is None:
                return False
    stored = str(row[0] or "").strip()
    kind = str(row[1] or "").strip()
    if kind != "instance" or not stored:
        connection.execute(
            text(
                f"UPDATE {_AUTH_RESTART_MARKER} "
                "SET instance_id = :boot, marker_kind = 'instance' WHERE id = 1"
            ),
            {"boot": boot_id},
        )
        connection.commit()
        return False
    if stored == boot_id:
        return False
    connection.execute(
        text(
            f"UPDATE {_AUTH_RESTART_MARKER} "
            "SET instance_id = :boot WHERE id = 1 AND marker_kind = 'instance'"
        ),
        {"boot": boot_id},
    )
    connection.commit()
    return True


def observe_postgres_restart_marker() -> bool:
    """Record this Postgres process. Connection failures leave the gate closed.

    Import and the owner gate itself do not connect. Seed-status calls this
    once a request is already being served. A failed read is not cached.
    """
    global _auth_restart_observed, _postgres_marker_checked
    if _is_sqlite or not _postgres_url(str(DATABASE_URL)):
        return bool(_auth_restart_observed)
    if _postgres_marker_checked:
        return bool(_auth_restart_observed)
    boot_id = current_auth_boot_id()
    if not boot_id:
        return False
    try:
        observed = apply_auth_restart_marker(engine, boot_id)
    except Exception:
        logger.warning("auth restart marker was not recorded")
        return False
    _auth_restart_observed = bool(observed)
    _postgres_marker_checked = True
    return bool(_auth_restart_observed)


def auth_store_is_durable() -> bool:
    return bool(_auth_store_durable)


def omit_casting_tables(tables):
    """Draft Nova Casting tables stay out of startup create_all.

    Disposable tests may create them with Table.create on an isolated engine.
    Production schema changes stay on the explicit Alembic revisions.
    """
    return [
        table for table in tables
        if not str(getattr(table, "name", "")).startswith("nova_casting_")
    ]


def _install_casting_create_all_guard() -> None:
    """Strip casting tables from every metadata.create_all, including explicit lists.

    Health ISF and deferred startup call create_all for the whole metadata.
    Importing the draft models must not create those tables on the live database.
    """
    metadata = Base.metadata
    if getattr(metadata, "_amicor_casting_create_all_guarded", False):
        return
    original = metadata.create_all

    def create_all(bind=None, tables=None, checkfirst=True, **kwargs):
        selected = metadata.sorted_tables if tables is None else tables
        return original(
            bind=bind,
            tables=omit_casting_tables(selected),
            checkfirst=checkfirst,
            **kwargs,
        )

    metadata.create_all = create_all  # type: ignore[method-assign]
    metadata._amicor_casting_create_all_guarded = True


_install_casting_create_all_guard()


def get_db():
    """FastAPI dependency: yields a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _sqlite_file_path() -> str | None:
    if not _is_sqlite or not str(DATABASE_URL).startswith("sqlite:///"):
        return None
    path = str(DATABASE_URL)[len("sqlite:///"):]
    if not path or path == ":memory:":
        return None
    return path


def init_platform_db() -> None:
    """Create SQLAlchemy-managed tables (idempotent, safe to run on startup).

    Customer-payment ledger tables are Alembic-only and are never created here.
    Draft Nova Casting tables are also omitted; Alembic applies them only outside production.
    """
    from app.db import models  # noqa: F401 — registers models with Base.metadata
    from app.core.nova.synapse import models as nova_synapse_models  # noqa: F401
    from app.core.nova.workspace import models as nova_workspace_models  # noqa: F401
    from app.core.nova.communications import models as nova_communications_models  # noqa: F401
    from app.core.nova.government import models as nova_government_models  # noqa: F401
    from app.core.nova.business import models as nova_business_models  # noqa: F401
    from app.core.nova.today import models as nova_today_models  # noqa: F401
    from app.core.nova.autonomy import models as nova_autonomy_models  # noqa: F401
    sqlite_path = _sqlite_file_path()
    if sqlite_path:
        os.makedirs(os.path.dirname(sqlite_path) or ".", exist_ok=True)
    payment_alembic_only = {"amicor_customer_payments", "amicor_customer_payment_events"}
    tables = omit_casting_tables(
        table for table in Base.metadata.sorted_tables if table.name not in payment_alembic_only
    )
    Base.metadata.create_all(bind=engine, tables=tables)
    from app.core.nova.freight.schema_ensure import ensure_nova_freight_schema
    from app.core.nova.today.schema_ensure import ensure_nova_today_schema
    from app.core.nova.autonomy.ledger import ensure_autonomy_schema
    ensure_nova_today_schema(engine)
    ensure_autonomy_schema(engine)
    ensure_nova_freight_schema(engine)


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
