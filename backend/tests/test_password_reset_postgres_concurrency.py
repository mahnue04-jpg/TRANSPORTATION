"""Temporary PostgreSQL-only concurrency test for password-reset finalization.

CI creates an ephemeral PostgreSQL container; no Render or customer data is used.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import User
from app.password_reset import PasswordResetToken, default_reset_expiry
from app.password_reset_service import _finalize_reset_delivery


@pytest.mark.skipif(
    not os.getenv("PASSWORD_RESET_TEST_POSTGRES_URL"),
    reason="Requires ephemeral PostgreSQL test container",
)
def test_simultaneous_accepted_emails_leave_one_active_link():
    url = os.environ["PASSWORD_RESET_TEST_POSTGRES_URL"]
    engine = create_engine(url, pool_size=4, max_overflow=2)
    try:
        User.__table__.create(engine, checkfirst=True)
        PasswordResetToken.__table__.create(engine, checkfirst=True)
        with Session(engine) as db:
            db.add(User(
                email="parallel-reset@example.org",
                hashed_password="offline-test-only",
                role="staff",
                is_active=True,
            ))
            db.add_all([
                PasswordResetToken(
                    email="parallel-reset@example.org",
                    token_hash="test-token-1",
                    expires_at=default_reset_expiry(),
                ),
                PasswordResetToken(
                    email="parallel-reset@example.org",
                    token_hash="test-token-2",
                    expires_at=default_reset_expiry(),
                ),
            ])
            db.commit()

        gate = Barrier(2, timeout=15)

        def finalize(token_hash: str):
            with Session(engine) as db:
                token = db.execute(
                    select(PasswordResetToken).where(
                        PasswordResetToken.token_hash == token_hash
                    )
                ).scalar_one()
                gate.wait()
                _finalize_reset_delivery(db, new_token=token, accepted=True)

        with ThreadPoolExecutor(max_workers=2) as workers:
            a = workers.submit(finalize, "test-token-1")
            b = workers.submit(finalize, "test-token-2")
            a.result(timeout=20)
            b.result(timeout=20)

        with Session(engine) as db:
            tokens = db.execute(select(PasswordResetToken)).scalars().all()
            assert len(tokens) == 2
            assert sum(token.used_at is None for token in tokens) == 1
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("PASSWORD_RESET_TEST_POSTGRES_URL"),
    reason="Requires ephemeral PostgreSQL test container",
)
def test_simultaneous_consumption_of_same_link_only_changes_password_once():
    """Two racing consumers must not both successfully reuse one reset token."""
    from app.db.models import RefreshToken
    from app.core.nova.signup.schema_ensure import ensure_nova_signup_schema
    from app.password_reset_service import apply_password_reset, hash_reset_token

    url = os.environ["PASSWORD_RESET_TEST_POSTGRES_URL"]
    engine = create_engine(url, pool_size=4, max_overflow=2)
    raw_token = "test-only-simultaneous-consumption"
    email = "same-token-concurrent@example.org"
    try:
        User.__table__.create(engine, checkfirst=True)
        RefreshToken.__table__.create(engine, checkfirst=True)
        PasswordResetToken.__table__.create(engine, checkfirst=True)
        ensure_nova_signup_schema(engine=engine)
        with Session(engine) as db:
            db.add(User(
                email=email,
                hashed_password="offline-old-hash",
                role="staff",
                is_active=True,
            ))
            db.add(PasswordResetToken(
                email=email,
                token_hash=hash_reset_token(raw_token),
                expires_at=default_reset_expiry(),
            ))
            db.commit()

        gate = Barrier(2, timeout=15)

        def consume(new_password: str):
            with Session(engine) as db:
                gate.wait()
                try:
                    return ("success", apply_password_reset(
                        db, token=raw_token, new_password=new_password,
                    ))
                except ValueError as exc:
                    db.rollback()
                    return ("rejected", str(exc))

        with ThreadPoolExecutor(max_workers=2) as workers:
            a = workers.submit(consume, "StrongFirstPass1!")
            b = workers.submit(consume, "StrongSecondPass2!")
            outcomes = [a.result(timeout=25), b.result(timeout=25)]

        assert sorted(x[0] for x in outcomes) == ["rejected", "success"]
        with Session(engine) as db:
            user = db.execute(select(User).where(User.email == email)).scalar_one()
            reset_row = db.execute(select(PasswordResetToken).where(
                PasswordResetToken.email == email
            )).scalar_one()
            assert user.auth_version == 1
            assert reset_row.used_at is not None
    finally:
        engine.dispose()
