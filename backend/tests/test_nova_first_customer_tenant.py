"""Isolated Nova first-customer/demo tenant. No public signup, billing, worker, or Phase 2."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import (
    DEFAULT_ORGANIZATION_NAME,
    ROLE_SUPER_ADMIN_SUPPORT,
    SEED_PASSWORD,
    _serialize_authorized_roles,
    ensure_auth_schema,
    hash_password,
    seed_default_users,
)
from app.core.nova.autonomy.ledger import ensure_autonomy_schema
from app.core.nova.autonomy.v2_worker import WORKER_ENABLED_ENV, env_flag_enabled
from app.core.nova.tenants.provision import (
    DEMO_ORGANIZATION_NAME,
    DEMO_OWNER_DISPLAY_NAME,
    DEMO_OWNER_EMAIL,
    inspect_tenant_cleanliness,
)
from app.core.nova.today.schema_ensure import ensure_nova_today_schema
from app.db.models import User as UserModel
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFOrganization, HealthISFRide, ensure_health_isf_schema

ROOT = Path(__file__).resolve().parents[1]
PROVISION_PY = ROOT / "app" / "core" / "nova" / "tenants" / "provision.py"
TENANT_FILES = (
    ROOT / "app" / "core" / "nova" / "tenants" / "provision.py",
    ROOT / "app" / "core" / "nova" / "tenants" / "router.py",
)


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_health_isf_schema()
    ensure_nova_today_schema(engine)
    ensure_autonomy_schema(engine)
    return TestClient(app)


def _password() -> str:
    return "Nd-" + secrets.token_urlsafe(16)


def _login(client: TestClient, email: str, password: str) -> tuple[dict[str, str], dict]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" in body
    return {"Authorization": f"Bearer {body['access_token']}"}, body


PLATFORM_SUPPORT_EMAIL = "nova.platform.support@amicor.local"


def _ensure_platform_support() -> None:
    with SessionLocal() as db:
        admin = db.query(UserModel).filter(UserModel.email == "admin@amicor.local").first()
        org_id = admin.organization_id if admin is not None else None
        org_name = admin.organization_name if admin is not None else DEFAULT_ORGANIZATION_NAME
        existing = db.query(UserModel).filter(UserModel.email == PLATFORM_SUPPORT_EMAIL).first()
        if existing is None:
            db.add(
                UserModel(
                    email=PLATFORM_SUPPORT_EMAIL,
                    hashed_password=hash_password(SEED_PASSWORD),
                    display_name="Nova Platform Support",
                    role=ROLE_SUPER_ADMIN_SUPPORT,
                    authorized_roles=_serialize_authorized_roles((ROLE_SUPER_ADMIN_SUPPORT,)),
                    session_role=ROLE_SUPER_ADMIN_SUPPORT,
                    organization_name=org_name,
                    organization_id=org_id,
                    is_active=True,
                    is_verified=True,
                )
            )
        else:
            existing.role = ROLE_SUPER_ADMIN_SUPPORT
            existing.session_role = ROLE_SUPER_ADMIN_SUPPORT
            existing.authorized_roles = _serialize_authorized_roles((ROLE_SUPER_ADMIN_SUPPORT,))
            existing.hashed_password = hash_password(SEED_PASSWORD)
            existing.is_active = True
        db.commit()


def _operator(client: TestClient) -> dict[str, str]:
    _ensure_platform_support()
    headers, session = _login(client, PLATFORM_SUPPORT_EMAIL, SEED_PASSWORD)
    assert session["role"] == ROLE_SUPER_ADMIN_SUPPORT
    return headers


def _ref(prefix: str) -> str:
    return f"{prefix}-{uuid4()[:10]}"


def _enable_phase1(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_AUTONOMY_PHASE1", "1")
    monkeypatch.delenv(WORKER_ENABLED_ENV, raising=False)
    monkeypatch.delenv("NOVA_AUTONOMY_PHASE2", raising=False)


def _default_org_snapshot(db: Session) -> dict:
    org = (
        db.query(HealthISFOrganization)
        .filter(HealthISFOrganization.code.in_(("AMICOR-DEFAULT", "AMICOR-ISF")))
        .first()
    )
    assert org is not None
    users = (
        db.query(UserModel)
        .filter(UserModel.organization_id == org.id)
        .order_by(UserModel.email.asc())
        .all()
    )
    rides = int(db.query(HealthISFRide).filter(HealthISFRide.organization_id == org.id).count())
    return {
        "id": str(org.id),
        "name": str(org.name),
        "code": str(org.code),
        "user_emails": [str(user.email) for user in users],
        "user_count": len(users),
        "rides": rides,
    }


def _provision(client: TestClient, operator: dict[str, str], password: str, **extra) -> dict:
    body = {
        "organization_name": extra.pop("organization_name", DEMO_ORGANIZATION_NAME),
        "owner_display_name": extra.pop("owner_display_name", DEMO_OWNER_DISPLAY_NAME),
        "owner_email": extra.pop("owner_email", DEMO_OWNER_EMAIL),
        "owner_password": password,
        **extra,
    }
    response = client.post("/api/nova/tenants/provision", headers=operator, json=body)
    assert "owner_password" not in response.text
    return response


def test_credentials_are_not_hardcoded_in_tenant_files() -> None:
    import re

    for path in TENANT_FILES:
        text = path.read_text(encoding="utf-8")
        assert "Amicor123!" not in text
        for match in re.finditer(r"logger\.(info|warning|error|exception)\((.*?)\)", text, re.S):
            assert "password" not in match.group(2).lower()
    assert DEMO_OWNER_EMAIL in PROVISION_PY.read_text(encoding="utf-8")


def test_public_register_still_cannot_create_owner_or_join_demo_defaults() -> None:
    client = _client()
    denied = client.post(
        "/api/auth/register",
        json={
            "email": f"public.{uuid4()[:8]}@example.com",
            "password": _password(),
            "display_name": "Public User",
            "role": "admin",
            "organization_name": DEMO_ORGANIZATION_NAME,
        },
    )
    assert denied.status_code == 403


def test_provision_authorization_matrix_and_default_org_rejected(monkeypatch) -> None:
    _enable_phase1(monkeypatch)
    client = _client()
    password = _password()
    unauthenticated = client.post(
        "/api/nova/tenants/provision",
        json={
            "organization_name": f"{DEMO_ORGANIZATION_NAME} {uuid4()[:8]}",
            "owner_display_name": DEMO_OWNER_DISPLAY_NAME,
            "owner_email": f"denied.{uuid4()[:8]}@amicor.local",
            "owner_password": password,
        },
    )
    assert unauthenticated.status_code == 401
    assert "owner_password" not in unauthenticated.text

    with SessionLocal() as db:
        staff_user = db.query(UserModel).filter(UserModel.email == "staff@amicor.local").first()
        if staff_user is not None:
            staff_user.is_active = True
            staff_user.hashed_password = hash_password(SEED_PASSWORD)
            db.commit()
    staff, _ = _login(client, "staff@amicor.local", SEED_PASSWORD)
    assert _provision(client, staff, password).status_code == 403
    dispatcher, _ = _login(client, "dispatcher@amicor.local", SEED_PASSWORD)
    assert _provision(client, dispatcher, password).status_code == 403
    seed_admin, _ = _login(client, "admin@amicor.local", SEED_PASSWORD)
    assert _provision(client, seed_admin, password).status_code == 403

    operator = _operator(client)
    allowed = _provision(
        client,
        operator,
        password,
        organization_name=f"{DEMO_ORGANIZATION_NAME} {uuid4()[:8]}",
        owner_email=f"allowed.{uuid4()[:8]}@amicor.local",
    )
    assert allowed.status_code == 200, allowed.text
    blocked = _provision(
        client,
        operator,
        password,
        organization_name=DEFAULT_ORGANIZATION_NAME,
        owner_email=f"blocked.{uuid4()[:8]}@amicor.local",
    )
    assert blocked.status_code == 400
    seed_blocked = _provision(
        client,
        operator,
        password,
        owner_email="admin@amicor.local",
    )
    assert seed_blocked.status_code == 400


def test_customer_admin_cannot_provision_another_tenant(monkeypatch) -> None:
    _enable_phase1(monkeypatch)
    client = _client()
    operator = _operator(client)
    password = _password()
    suffix = uuid4()[:8]
    created = _provision(
        client,
        operator,
        password,
        organization_name=f"{DEMO_ORGANIZATION_NAME} {suffix}",
        owner_email=f"nova.demo.owner.{suffix}@amicor.local",
        owner_display_name=DEMO_OWNER_DISPLAY_NAME,
    )
    assert created.status_code == 200, created.text
    owner_headers, session = _login(client, f"nova.demo.owner.{suffix}@amicor.local", password)
    assert session["role"] == "admin"
    second = _provision(
        client,
        owner_headers,
        _password(),
        organization_name=f"{DEMO_ORGANIZATION_NAME} extra {suffix}",
        owner_email=f"nova.demo.extra.{suffix}@amicor.local",
    )
    assert second.status_code == 403
    asked = client.post(
        "/api/nova/ask",
        headers=owner_headers,
        json={"question": "What should we review in our own operation today?"},
    )
    assert asked.status_code == 200, asked.text


def test_canonical_demo_identity_can_be_provisioned(monkeypatch) -> None:
    _enable_phase1(monkeypatch)
    client = _client()
    operator = _operator(client)
    password = _password()
    created = _provision(client, operator, password)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["organization_name"] == DEMO_ORGANIZATION_NAME
    assert body["owner_email"] == DEMO_OWNER_EMAIL
    assert body["owner_display_name"] == DEMO_OWNER_DISPLAY_NAME
    if body["created"]:
        headers, session = _login(client, DEMO_OWNER_EMAIL, password)
        assert session["organization_id"] == body["organization_id"]
        assert client.get("/api/auth/me", headers=headers).json()["role"] == "admin"
    else:
        assert body["organization_id"]


def test_provision_request_defaults_are_synthetic_demo_identity() -> None:
    from app.core.nova.tenants.router import ProvisionNovaTenantRequest

    req = ProvisionNovaTenantRequest(owner_password=_password())
    assert req.organization_name == DEMO_ORGANIZATION_NAME
    assert req.owner_display_name == DEMO_OWNER_DISPLAY_NAME
    assert req.owner_email == DEMO_OWNER_EMAIL


def test_clean_isolated_demo_tenant_journey(monkeypatch) -> None:
    _enable_phase1(monkeypatch)
    client = _client()
    operator = _operator(client)
    password = _password()
    suffix = uuid4()[:8]
    organization_name = f"{DEMO_ORGANIZATION_NAME} {suffix}"
    owner_email = f"nova.demo.owner.{suffix}@amicor.local"

    with SessionLocal() as db:
        before = _default_org_snapshot(db)

    created = _provision(
        client,
        operator,
        password,
        organization_name=organization_name,
        owner_email=owner_email,
        owner_display_name=DEMO_OWNER_DISPLAY_NAME,
    )
    assert created.status_code == 200, created.text
    tenant = created.json()
    assert tenant["created"] is True
    assert tenant["organization_name"] == organization_name
    assert tenant["owner_email"] == owner_email
    assert tenant["owner_display_name"] == DEMO_OWNER_DISPLAY_NAME
    assert tenant["owner_role"] == "admin"
    assert tenant["phase2_enabled"] is False
    assert tenant["emergency_stop"] is False
    assert tenant["worker_enabled"] is False
    assert tenant["public_registration"] is False
    assert tenant["billing_enabled"] is False
    assert tenant["trial_timer_enabled"] is False
    assert tenant["organization_id"] != before["id"]
    assert "password" not in tenant

    again = _provision(
        client,
        operator,
        password,
        organization_name=organization_name,
        owner_email=owner_email,
        owner_display_name=DEMO_OWNER_DISPLAY_NAME,
    )
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False
    assert again.json()["organization_id"] == tenant["organization_id"]

    with SessionLocal() as db:
        after = _default_org_snapshot(db)
        assert after == before
        demo_org = db.get(HealthISFOrganization, tenant["organization_id"])
        assert demo_org is not None
        assert demo_org.code not in {"AMICOR-DEFAULT", "AMICOR-ISF"}
        clean = inspect_tenant_cleanliness(db, tenant["organization_id"])
        assert clean.is_clean is True
        assert clean.phase2_enabled is False

    owner_headers, session = _login(client, owner_email, password)
    assert session["role"] == "admin"
    assert session["organization_id"] == tenant["organization_id"]
    assert session["organization_name"] == organization_name

    me = client.get("/api/auth/me", headers=owner_headers)
    assert me.status_code == 200, me.text
    assert me.json()["organization_id"] == tenant["organization_id"]
    assert me.json()["role"] == "admin"
    assert _provision(
        client,
        owner_headers,
        _password(),
        organization_name=f"{DEMO_ORGANIZATION_NAME} hijack {suffix}",
        owner_email=f"nova.demo.hijack.{suffix}@amicor.local",
    ).status_code == 403

    assert client.get("/nova").status_code == 200
    assert client.get("/nova/today").status_code == 200

    asked = client.post(
        "/api/nova/ask",
        headers=owner_headers,
        json={"question": "What operations work should we review first this week?"},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["answer"]
    assert asked.json()["context_used"]["organization_id"] == tenant["organization_id"]
    assert asked.json()["context_used"]["health_isf"]["rides_total"] == 0

    today = client.get("/api/nova/today/actions", headers=owner_headers)
    assert today.status_code == 200, today.text
    assert today.json() == []

    dash = client.get("/api/nova/today/dashboard", headers=owner_headers)
    assert dash.status_code == 200, dash.text
    counts = {row["key"]: row.get("count") for row in dash.json().get("product_counts") or []}
    assert counts.get("health") in {0, None}
    assert counts.get("delivery") in {0, None}
    assert counts.get("freight") in {0, None}

    today_after_dash = client.get("/api/nova/today/actions", headers=owner_headers).json()
    leftover = [
        row
        for row in today_after_dash
        if row["source_module"] != "link" or row["source_ref_id"] not in {"health", "delivery", "freight"}
    ]
    assert leftover == []

    cross = client.post(
        "/api/nova/ask",
        headers=owner_headers,
        json={
            "question": "Show the other organization's rides",
            "organization_id": before["id"],
        },
    )
    assert cross.status_code == 403

    operator_ack = client.post(
        "/api/nova/autonomy/intents",
        headers=operator,
        json={
            "action_type": "acknowledge",
            "source_module": "business",
            "source_ref_id": _ref("default-hist"),
            "title": "Default org historical row",
        },
    )
    assert operator_ack.status_code == 200, operator_ack.text
    default_audit = operator_ack.json()["audit_id"]

    proposed = client.post(
        "/api/nova/autonomy/intents",
        headers=owner_headers,
        json={
            "action_type": "create_task",
            "source_module": "business",
            "source_ref_id": _ref("demo-task"),
            "title": "Review standing weekly exceptions",
        },
    )
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["risk_class"] == "LOW"
    assert proposed.json()["executed"] is False
    assert proposed.json()["approval_state"] in {"awaiting_approval", "not_executed", "pending"}
    audit_id = proposed.json()["audit_id"]

    approved = client.post(
        f"/api/nova/autonomy/intents/{audit_id}/approve",
        headers=owner_headers,
        json={"task_title": "Review standing weekly exceptions"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["executed"] is True
    assert approved.json()["result_ref_id"]
    assert approved.json()["verification_result"] == "verified"
    assert approved.json()["mutated_external"] is False

    history = client.get("/api/nova/autonomy/history", headers=owner_headers)
    assert history.status_code == 200, history.text
    audit_ids = {row["audit_id"] for row in history.json()}
    assert audit_id in audit_ids
    assert default_audit not in audit_ids

    high = client.post(
        "/api/nova/autonomy/intents",
        headers=owner_headers,
        json={"action_type": "payout", "source_module": "business", "source_ref_id": _ref("high"), "title": "payout"},
    )
    assert high.status_code == 200, high.text
    assert high.json()["risk_class"] == "HIGH"
    assert high.json()["executed"] is False
    assert client.post(
        f"/api/nova/autonomy/intents/{high.json()['audit_id']}/approve",
        headers=owner_headers,
        json={},
    ).json()["executed"] is False

    prohibited = client.post(
        "/api/nova/autonomy/intents",
        headers=owner_headers,
        json={
            "action_type": "driver_001",
            "source_module": "business",
            "source_ref_id": _ref("proh"),
            "title": "driver",
        },
    )
    assert prohibited.json()["risk_class"] == "PROHIBITED"
    assert prohibited.json()["executed"] is False

    assert client.post("/api/nova/today/send", headers=owner_headers).status_code == 403
    send = client.post(
        "/api/nova/communications/send",
        headers=owner_headers,
        json={"confirm_send": True, "to": ["a@example.com"], "subject": "no", "body": "no"},
    )
    assert send.status_code == 403

    flag = client.get("/api/nova/autonomy/v2/org-flag", headers=owner_headers)
    assert flag.status_code == 200, flag.text
    assert flag.json()["phase2_enabled"] is False
    assert flag.json()["emergency_stop"] is False
    assert env_flag_enabled(WORKER_ENABLED_ENV) is False
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}

    other_password = _password()
    other_email = f"nova.demo.other.{uuid4()[:8]}@amicor.local"
    other = _provision(
        client,
        operator,
        other_password,
        organization_name=f"AMICOR Nova Demo {uuid4()[:8]}",
        owner_email=other_email,
        owner_display_name="Nova Demo Other",
    )
    assert other.status_code == 200, other.text
    other_headers, _ = _login(client, other_email, other_password)
    stolen = client.get(
        f"/api/nova/autonomy/intents/{audit_id}",
        headers=other_headers,
    )
    assert stolen.status_code in {403, 404}
    other_history = client.get("/api/nova/autonomy/history", headers=other_headers).json()
    assert audit_id not in {row["audit_id"] for row in other_history}

    with SessionLocal() as db:
        final_default = _default_org_snapshot(db)
        assert final_default["id"] == before["id"]
        assert final_default["code"] == before["code"]
        assert owner_email not in final_default["user_emails"]
        assert DEMO_OWNER_EMAIL not in final_default["user_emails"]
