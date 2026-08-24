"""Alembic environment — reads DATABASE_URL from env, imports ORM Base."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Make sure the backend app package is importable ─────────────────────────
# (alembic is run from the backend/ directory)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.session import Base, DATABASE_URL  # noqa: E402
import app.db.models  # noqa: F401, E402 — registers all ORM models with Base
import app.modules.health_isf.models  # noqa: F401, E402 — include Health ISF metadata
import app.modules.payments.models  # noqa: F401, E402 — Ride + Deliver payment ledger

# ── Alembic Config object ────────────────────────────────────────────────────
config = context.config

# Inject the runtime DATABASE_URL so alembic.ini can stay url-free
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Set up Python loggers as defined in alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    """Limit autogeneration to SQLAlchemy-managed platform and health_isf tables."""
    if type_ == "table":
        if name == "alembic_version":
            return True
        return (
            name.startswith("platform_")
            or name.startswith("health_isf_")
            or name.startswith("amicor_")
        )
    return True


# ── Run migrations ───────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """Run in 'offline' mode — produce SQL script without a DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run in 'online' mode — connect to DB and apply migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
