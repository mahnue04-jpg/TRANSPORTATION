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
@pytest.mark.parametrize("request_count", [2, 3, 5])
def test_simultaneous_accepted_emails_leave_one_active_link(request_count):
    """All contenders start together; one valid link remains after finalization."""
    url = os.environ["PASSWORD_RESET_TEST_POSTGRES_URL"]
    engine = create_engine(url, pool_size=max(request_count + 1, 6), max_overflow=2)
    email = f"parallel-reset-{request_count}@example.org"
    hashes = [f"test-token-{request_count}-{i}" for i in range(request_count)]
    try:
        User.__table__.create(engine, checkfirst=True)
        PasswordResetToken.__table__.create(engine, checkfirst=True)
        with Session(engine) as db:
            db.add(User(
                email=email,
                hashed_password="offline-test-only",
                role="staff",
                is_active=True,
            ))
            db.add_all([
                PasswordResetToken(
                    email=email,
                    token_hash=token_hash,
                    expires_at=default_reset_expiry(),
                )
                for token_hash in hashes
            ])
            db.commit()

        gate = Barrier(request_count, timeout=20)

        def finalize(token_hash: str):
            with Session(engine) as db:
                token = db.execute(
                    select(PasswordResetToken).where(
                        PasswordResetToken.token_hash == token_hash
                    )
                ).scalar_one()
                gate.wait()
                _finalize_reset_delivery(db, new_token=token, accepted=True)

        with ThreadPoolExecutor(max_workers=request_count) as workers:
            futures = [workers.submit(finalize, token_hash) for token_hash in hashes]
            for future in futures:
                future.result(timeout=30)

        with Session(engine) as db:
            tokens = db.execute(
                select(PasswordResetToken).where(PasswordResetToken.email == email)
            ).scalars().all()
            assert len(tokens) == request_count
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


@pytest.mark.skipif(
    not os.getenv("PASSWORD_RESET_TEST_POSTGRES_URL"),
    reason="Requires ephemeral PostgreSQL test container",
)
@pytest.mark.parametrize("accepted_results", [(True, False), (False, False)])
def test_overlapping_accepted_and_failed_messages_preserve_a_link(accepted_results):
    """A failed mail attempt never retires an earlier usable recovery link."""
    url = os.environ["PASSWORD_RESET_TEST_POSTGRES_URL"]
    engine = create_engine(url, pool_size=5, max_overflow=2)
    suffix = "-".join("yes" if accepted else "no" for accepted in accepted_results)
    email = f"mixed-mail-{suffix}@example.org"
    original_hash = f"existing-{suffix}"
    hashes = [f"replacement-{suffix}-{i}" for i in range(2)]
    try:
        User.__table__.create(engine, checkfirst=True)
        PasswordResetToken.__table__.create(engine, checkfirst=True)
        with Session(engine) as db:
            db.add(User(
                email=email, hashed_password="offline-test-only",
                role="staff", is_active=True,
            ))
            db.add_all([
                PasswordResetToken(
                    email=email, token_hash=token_hash,
                    expires_at=default_reset_expiry(),
                )
                for token_hash in [original_hash, *hashes]
            ])
            db.commit()

        gate = Barrier(2, timeout=15)

        def finalize(token_hash: str, accepted: bool):
            with Session(engine) as db:
                token = db.execute(select(PasswordResetToken).where(
                    PasswordResetToken.token_hash == token_hash
                )).scalar_one()
                gate.wait()
                _finalize_reset_delivery(db, new_token=token, accepted=accepted)

        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [
                workers.submit(finalize, token_hash, accepted)
                for token_hash, accepted in zip(hashes, accepted_results)
            ]
            for future in futures:
                future.result(timeout=25)

        with Session(engine) as db:
            rows = db.execute(select(PasswordResetToken).where(
                PasswordResetToken.email == email
            )).scalars().all()
            active = [row.token_hash for row in rows if row.used_at is None]
            expected = [hashes[0]] if accepted_results[0] else [original_hash]
            assert active == expected
            assert len(rows) == (2 if accepted_results[0] else 1)
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("PASSWORD_RESET_TEST_POSTGRES_URL"),
    reason="Requires ephemeral PostgreSQL test container",
)
@pytest.mark.parametrize("request_count", [2, 5])
def test_overlapping_pending_email_acceptances_activate_only_one_link(request_count):
    """Start all replacement links expired, as production does before mail acceptance."""
    from app.helpers import now
    from app.password_reset import token_is_expired

    url = os.environ["PASSWORD_RESET_TEST_POSTGRES_URL"]
    engine = create_engine(url, pool_size=request_count + 2, max_overflow=2)
    email = f"pending-concurrent-{request_count}@example.org"
    original_hash = f"old-valid-{request_count}"
    hashes = [f"new-pending-{request_count}-{i}" for i in range(request_count)]
    try:
        User.__table__.create(engine, checkfirst=True)
        PasswordResetToken.__table__.create(engine, checkfirst=True)
        with Session(engine) as db:
            db.add(User(email=email, hashed_password="offline-test-only",
                        role="staff", is_active=True))
            db.add(PasswordResetToken(email=email, token_hash=original_hash,
                                     expires_at=default_reset_expiry()))
            for token_hash in hashes:
                db.add(PasswordResetToken(email=email, token_hash=token_hash,
                                          expires_at=now()))
            db.commit()

        gate = Barrier(request_count, timeout=20)

        def finalize(token_hash):
            with Session(engine) as db:
                token = db.execute(select(PasswordResetToken).where(
                    PasswordResetToken.token_hash == token_hash
                )).scalar_one()
                gate.wait()
                _finalize_reset_delivery(db, new_token=token, accepted=True)

        with ThreadPoolExecutor(max_workers=request_count) as pool:
            futures = [pool.submit(finalize, value) for value in hashes]
            for future in futures:
                future.result(timeout=30)

        with Session(engine) as db:
            rows = db.execute(select(PasswordResetToken).where(
                PasswordResetToken.email == email
            )).scalars().all()
            valid = [row.token_hash for row in rows
                     if row.used_at is None and not token_is_expired(row.expires_at)]
            assert len(rows) == request_count + 1
            assert len(valid) == 1
            assert valid[0] in hashes
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("PASSWORD_RESET_TEST_POSTGRES_URL"),
    reason="Requires ephemeral PostgreSQL test container",
)
def test_interrupted_email_leaves_pending_token_unusable_on_postgres():
    """An unfinalized persisted token must not change credentials."""
    from app.helpers import now
    from app.db.models import RefreshToken
    from app.core.nova.signup.schema_ensure import ensure_nova_signup_schema
    from app.password_reset_service import apply_password_reset, hash_reset_token

    url = os.environ["PASSWORD_RESET_TEST_POSTGRES_URL"]
    engine = create_engine(url)
    email = "interrupted-email@example.org"
    pending = "pending-never-accepted-test-token"
    try:
        User.__table__.create(engine, checkfirst=True)
        RefreshToken.__table__.create(engine, checkfirst=True)
        PasswordResetToken.__table__.create(engine, checkfirst=True)
        ensure_nova_signup_schema(engine=engine)
        with Session(engine) as db:
            db.add(User(email=email, hashed_password="unchanged-test-hash",
                        role="staff", is_active=True))
            db.add(PasswordResetToken(
                email=email, token_hash=hash_reset_token(pending),
                expires_at=now(),
            ))
            db.commit()

        # Simulates a process crash after persisting the pending token but
        # before the provider response/finalization. Use a fresh transaction.
        with Session(engine) as db:
            with pytest.raises(ValueError, match="Invalid or expired reset link"):
                apply_password_reset(
                    db, token=pending, new_password="StrongPendingPass1!"
                )
            db.rollback()

        with Session(engine) as db:
            user = db.execute(select(User).where(User.email == email)).scalar_one()
            assert user.hashed_password == "unchanged-test-hash"
            assert user.auth_version == 0
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("PASSWORD_RESET_TEST_POSTGRES_URL"),
    reason="Requires ephemeral PostgreSQL test container",
)
def test_email_accepted_after_password_change_cannot_reactivate_old_link():
    """A queued email belongs to the credential generation at request time."""
    from app.helpers import now
    from app.password_reset import token_is_expired

    engine = create_engine(os.environ["PASSWORD_RESET_TEST_POSTGRES_URL"])
    email = "delayed-acceptance-after-reset@example.org"
    try:
        User.__table__.create(engine, checkfirst=True)
        PasswordResetToken.__table__.create(engine, checkfirst=True)
        with Session(engine) as db:
            db.add(User(email=email, hashed_password="changed-credentials",
                        role="staff", is_active=True, auth_version=2))
            db.add(PasswordResetToken(email=email, token_hash="stale-pending",
                                      expires_at=now()))
            db.commit()

        with Session(engine) as db:
            token = db.execute(select(PasswordResetToken).where(
                PasswordResetToken.token_hash == "stale-pending"
            )).scalar_one()
            _finalize_reset_delivery(
                db, new_token=token, accepted=True, expected_auth_version=1,
            )
        with Session(engine) as db:
            token = db.execute(select(PasswordResetToken).where(
                PasswordResetToken.token_hash == "stale-pending"
            )).scalar_one_or_none()
            assert token is None or token.used_at is not None or token_is_expired(token.expires_at)
            user = db.execute(select(User).where(User.email == email)).scalar_one()
            assert user.auth_version == 2
    finally:
        engine.dispose()
