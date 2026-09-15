"""Ask Nova must recover after swallowed Today SQL errors poison the session."""
from __future__ import annotations

from sqlalchemy import text
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, UserContext, ensure_auth_schema, seed_default_users
from app.core.nova.today.db_recovery import recover_today_session
from app.core.nova.today.service import list_recheck_events
from app.main import app


def _client() -> TestClient:
    from app.core.nova.today.schema_ensure import ensure_nova_today_schema
    from app.db.session import engine, init_platform_db

    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_nova_today_schema(engine)
    return TestClient(app)


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _poison_count(db, organization_id: str) -> int:
    db.execute(text("SELECT * FROM nova_today_tx_probe_missing_relation"))
    return 0


def test_recover_today_session_allows_recheck_query_after_sql_failure() -> None:
    from app.db.session import SessionLocal

    _client()
    with SessionLocal() as db:
        try:
            db.execute(text("SELECT * FROM nova_today_tx_probe_missing_relation"))
        except Exception:
            recover_today_session(db)
        user = UserContext(
            user_id="tx-probe-owner",
            email="dispatcher@amicor.local",
            role="dispatcher",
            organization_id="org-tx-probe",
            organization_name="TX Probe",
        )
        rows = list_recheck_events(db, organization_id="org-tx-probe", user=user, limit=4)
        assert rows == []


def test_swallowed_product_count_sql_failure_does_not_fail_ask(monkeypatch) -> None:
    from app.core.nova.today import service

    client = _client()
    recovered: list[bool] = []
    real_recover = service.recover_today_session

    def tracking_recover(db):
        recovered.append(True)
        return real_recover(db)

    monkeypatch.setattr(service, "recover_today_session", tracking_recover)
    monkeypatch.setattr(service, "_count_health_active_rides", _poison_count)
    monkeypatch.setattr(service, "_count_delivery_open_requests", _poison_count)
    monkeypatch.setattr(service, "_count_freight_active_shipments", _poison_count)

    asked = client.post(
        "/api/nova/today/ask",
        headers=_headers(client),
        json={"question": "What needs my attention today?"},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["answer"]
    assert recovered
    history = client.get("/api/nova/today/history", headers=_headers(client))
    assert history.status_code == 200, history.text


def test_swallowed_source_sql_failure_does_not_fail_ask(monkeypatch) -> None:
    from app.core.nova.today import service
    from app.core.nova.workspace import service as workspace_service

    client = _client()

    def boom(db, organization_id, user):
        db.execute(text("SELECT * FROM nova_today_source_tx_probe_missing"))
        raise AssertionError("poisoned source query should raise")

    monkeypatch.setattr(workspace_service, "dashboard", boom)

    asked = client.post(
        "/api/nova/today/ask",
        headers=_headers(client),
        json={"question": "What needs my attention today?"},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["answer"]
