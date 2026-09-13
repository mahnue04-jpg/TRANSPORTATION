"""Phase 2E adapter layer. No worker, Phase 2 flag, or widened permissions."""
from __future__ import annotations

import ast
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.autonomy.models import (
    NovaAutonomyExecutionAttempt,
    NovaAutonomyLedger,
    NovaAutonomyWorkflow,
    NovaAutonomyWorkflowStep,
)
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import now, uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
AUTONOMY = ROOT / "app" / "core" / "nova" / "autonomy"
WORKER_MARKERS = ("apscheduler", "celery", "backgroundscheduler", "cron", "while true")
FORBIDDEN_MODULES = (
    "rider_checkout",
    "stripe_payments",
    "financial_engine",
    "health_isf",
    "app.modules.payments",
)


def _client() -> TestClient:
    from app.core.nova.autonomy.ledger import ensure_autonomy_schema
    from app.core.nova.today.schema_ensure import ensure_nova_today_schema

    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_nova_today_schema(engine)
    ensure_autonomy_schema(engine)
    return TestClient(app)


def _login(client: TestClient, email: str = "admin@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create(client: TestClient, headers: dict[str, str], **extra):
    body = {
        "workflow_type": extra.pop("workflow_type", "research_draft_task"),
        "initiating_module": extra.pop("initiating_module", "today"),
        "source_ref_id": extra.pop("source_ref_id", f"p2e-{uuid4()[:10]}"),
    }
    body.update(extra)
    return client.post("/api/nova/autonomy/v2/workflows", headers=headers, json=body)


def _insert_step(
    workflow_id: str,
    organization_id: str,
    *,
    action_type: str,
    risk_class: str,
    step_id: str,
    source_module: str,
    target_module: str | None = None,
) -> None:
    with SessionLocal() as db:
        db.add(
            NovaAutonomyWorkflowStep(
                step_id=step_id,
                workflow_id=workflow_id,
                organization_id=organization_id,
                sequence_number=1,
                source_module=source_module,
                target_module=target_module or source_module,
                action_type=action_type,
                risk_class=risk_class,
                status="waiting",
                idempotency_key=f"{workflow_id}-{action_type}-{step_id[-6:]}",
                created_at=now(),
                updated_at=now(),
            )
        )
        row = db.get(NovaAutonomyWorkflow, workflow_id)
        assert row is not None
        row.status = "waiting"
        row.current_step = step_id
        db.commit()


def _approve_step(client: TestClient, headers: dict[str, str], workflow_id: str, step_id: str, **params):
    return client.post(
        f"/api/nova/autonomy/v2/workflows/{workflow_id}/steps/{step_id}/approve",
        headers=headers,
        params=params,
    )


def test_allowed_low_adapter_path_requires_owner_and_is_idempotent() -> None:
    client = _client()
    owner = _login(client)
    dispatcher = _login(client, "dispatcher@amicor.local")
    created = _create(client, owner, source_ref_id=f"low-{uuid4()[:8]}")
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow_id"]
    org_id = created.json()["organization_id"]
    _insert_step(
        workflow_id,
        org_id,
        action_type="history",
        risk_class="LOW",
        step_id="NWS-ADAPTERLOW001",
        source_module="today",
    )
    denied = _approve_step(client, dispatcher, workflow_id, "NWS-ADAPTERLOW001")
    assert denied.status_code == 403
    parked = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=owner)
    assert parked.json()["status"] == "waiting"
    assert parked.json()["executed"] is False
    first = _approve_step(client, owner, workflow_id, "NWS-ADAPTERLOW001")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "completed"
    assert first.json()["mutated_external"] is False
    ref = first.json()["steps"][0]["result_ref_id"]
    assert ref.startswith("ADP-")
    replay = _approve_step(client, owner, workflow_id, "NWS-ADAPTERLOW001")
    assert replay.status_code == 200
    assert replay.json()["steps"][0]["result_ref_id"] == ref
    again = _approve_step(client, owner, workflow_id, "NWS-ADAPTERLOW001")
    assert again.json()["steps"][0]["result_ref_id"] == ref
    with SessionLocal() as db:
        attempts = (
            db.query(NovaAutonomyExecutionAttempt)
            .filter(NovaAutonomyExecutionAttempt.step_id == "NWS-ADAPTERLOW001")
            .all()
        )
        assert len(attempts) == 1
        rows = db.query(NovaAutonomyLedger).filter(NovaAutonomyLedger.workflow_id == workflow_id).all()
        assert rows
        assert all("secret" not in str(row.detail or "").lower() for row in rows)
        assert all("sk_" not in str(row.detail or "") for row in rows)

    health = _create(client, owner, source_ref_id=f"href-{uuid4()[:8]}")
    _insert_step(
        health.json()["workflow_id"],
        health.json()["organization_id"],
        action_type="history",
        risk_class="LOW",
        step_id="NWS-ADAPTHEALTHR1",
        source_module="health",
    )
    rec = _approve_step(client, owner, health.json()["workflow_id"], "NWS-ADAPTHEALTHR1")
    assert rec.status_code == 200, rec.text
    assert rec.json()["status"] == "completed"
    assert rec.json()["mutated_external"] is False
    assert rec.json()["steps"][0]["result_ref_id"].startswith("ADP-")


def test_medium_parked_high_prohibited_unknowns_and_writes_blocked() -> None:
    client = _client()
    owner = _login(client)
    medium = _create(client, owner, source_ref_id=f"med-{uuid4()[:8]}")
    _insert_step(
        medium.json()["workflow_id"],
        medium.json()["organization_id"],
        action_type="send_email",
        risk_class="MEDIUM",
        step_id="NWS-ADAPTMEDIUM1",
        source_module="communications",
    )
    parked = _approve_step(client, owner, medium.json()["workflow_id"], "NWS-ADAPTMEDIUM1")
    assert parked.status_code == 200, parked.text
    assert parked.json()["status"] == "waiting"
    assert parked.json()["executed"] is False
    assert parked.json()["steps"][0]["status"] == "awaiting_approval"
    assert parked.json()["steps"][0]["result_ref_id"] is None

    high = _create(client, owner, source_ref_id=f"high-{uuid4()[:8]}")
    _insert_step(
        high.json()["workflow_id"],
        high.json()["organization_id"],
        action_type="payout",
        risk_class="HIGH",
        step_id="NWS-ADAPTHIGH0001",
        source_module="payments_readiness",
    )
    blocked = _approve_step(client, owner, high.json()["workflow_id"], "NWS-ADAPTHIGH0001")
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked_by_policy"
    assert blocked.json()["executed"] is False

    unknown_module = _create(client, owner, source_ref_id=f"umod-{uuid4()[:8]}")
    _insert_step(
        unknown_module.json()["workflow_id"],
        unknown_module.json()["organization_id"],
        action_type="history",
        risk_class="LOW",
        step_id="NWS-ADAPTUNKMOD1",
        source_module="not_a_module",
    )
    missing_module = _approve_step(client, owner, unknown_module.json()["workflow_id"], "NWS-ADAPTUNKMOD1")
    assert missing_module.status_code == 409

    unknown_action = _create(client, owner, source_ref_id=f"uact-{uuid4()[:8]}")
    _insert_step(
        unknown_action.json()["workflow_id"],
        unknown_action.json()["organization_id"],
        action_type="invent_new_side_effect",
        risk_class="PROHIBITED",
        step_id="NWS-ADAPTUNKACT1",
        source_module="today",
    )
    missing_action = _approve_step(client, owner, unknown_action.json()["workflow_id"], "NWS-ADAPTUNKACT1")
    assert missing_action.status_code == 200
    assert missing_action.json()["status"] == "blocked_by_policy"

    for module, step_id, action in (
        ("health", "NWS-ADAPTHEALTH1", "create_draft"),
        ("delivery", "NWS-ADAPTDELIV01", "create_draft"),
        ("freight", "NWS-ADAPTFREIGHT1", "create_draft"),
        ("accounting", "NWS-ADAPTACCT0001", "create_draft"),
        ("payments_readiness", "NWS-ADAPTPAY0001", "create_draft"),
    ):
        created = _create(client, owner, source_ref_id=f"{module}-{uuid4()[:6]}")
        _insert_step(
            created.json()["workflow_id"],
            created.json()["organization_id"],
            action_type=action,
            risk_class="LOW",
            step_id=step_id,
            source_module=module,
        )
        denied = _approve_step(client, owner, created.json()["workflow_id"], step_id)
        assert denied.status_code == 200, denied.text
        assert denied.json()["status"] == "blocked_by_policy"
        assert denied.json()["executed"] is False
        assert denied.json()["steps"][0]["result_ref_id"] is None


def test_cross_org_denied_adapter_failure_and_driver_blocked() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"xorg-{uuid4()[:8]}")
    workflow_id = created.json()["workflow_id"]
    _insert_step(
        workflow_id,
        created.json()["organization_id"],
        action_type="history",
        risk_class="LOW",
        step_id="NWS-ADAPTXORG0001",
        source_module="today",
    )
    foreign = _approve_step(
        client,
        owner,
        workflow_id,
        "NWS-ADAPTXORG0001",
        organization_id="org-not-the-caller",
    )
    assert foreign.status_code == 403
    visible = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=owner)
    assert visible.status_code == 200
    assert visible.json()["status"] == "waiting"

    failed = _create(client, owner, source_ref_id="adapter-fail-closed")
    _insert_step(
        failed.json()["workflow_id"],
        failed.json()["organization_id"],
        action_type="history",
        risk_class="LOW",
        step_id="NWS-ADAPTFAIL0001",
        source_module="today",
    )
    stopped = _approve_step(client, owner, failed.json()["workflow_id"], "NWS-ADAPTFAIL0001")
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "failed"
    assert stopped.json()["executed"] is False
    assert stopped.json()["steps"][0]["result_ref_id"] is None

    driver = _create(client, owner, source_ref_id=f"d001-{uuid4()[:8]}")
    _insert_step(
        driver.json()["workflow_id"],
        driver.json()["organization_id"],
        action_type="driver_001",
        risk_class="PROHIBITED",
        step_id="NWS-ADAPTDRV00101",
        source_module="today",
    )
    blocked = _approve_step(client, owner, driver.json()["workflow_id"], "NWS-ADAPTDRV00101")
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked_by_policy"
    assert blocked.json()["executed"] is False


def test_direct_routes_remain_blocked_and_no_worker() -> None:
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    client = _client()
    owner = _login(client)
    for path in ("/api/nova/today/send", "/api/nova/today/file", "/api/nova/today/call"):
        assert client.post(path, headers=owner).status_code == 403
    pay = client.post("/api/nova/today/ledger", headers=owner)
    assert pay.status_code == 403
    send = client.post(
        "/api/nova/communications/send",
        headers=owner,
        json={"confirm_send": True, "to": ["a@example.com"], "subject": "no", "body": "no"},
    )
    assert send.status_code == 403
    payout = client.post(
        "/api/nova/autonomy/v2/workflows",
        headers=owner,
        json={
            "workflow_type": "research_draft_task",
            "initiating_module": "today",
            "source_ref_id": f"pay-{uuid4()[:8]}",
            "action_type": "payout",
        },
    )
    assert payout.status_code == 400
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    for path in AUTONOMY.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert all(marker not in text for marker in WORKER_MARKERS), path.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            else:
                continue
            assert all(banned not in module for banned in FORBIDDEN_MODULES), f"{path.name} imports {module}"
