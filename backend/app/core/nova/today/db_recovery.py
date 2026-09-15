"""Recover a poisoned SQLAlchemy session after a swallowed Today DB error."""
from __future__ import annotations

from sqlalchemy.orm import Session


def recover_today_session(db: Session | None) -> None:
    """Roll back an aborted transaction so later Today reads can proceed."""
    if db is None:
        return
    try:
        db.rollback()
    except Exception:
        return
