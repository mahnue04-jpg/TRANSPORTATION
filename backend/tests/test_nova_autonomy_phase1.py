"""Autonomy Phase 1: supervised LOW execution, MEDIUM records, HIGH/PROHIBITED blocked."""
from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.helpers import uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
AUTONOMY = ROOT / "app" / "core" / "nova" / "autonomy"
NOVA_TABS = (
    "/nova",
    "/nova/today",
    "/nova/workspace",
    "/nova/communications",
    "/nova/government",
    "/nova/business",
    "/nova/accounting",
    "/nova/accounting/aging",
    "/nova/accounting/trends",
    "/nova/payments/readiness",
    "/nova/freight",
    "/workspace",
    "/app",
)
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
    from app.db.session import engine, init_platform_db

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


def _enable(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_AUTONOMY_PHASE1", "1")


def _ref(prefix: str) -> str:
    return f"{prefix}-{uuid4()[:10]}"


def _create(client: TestClient, headers: dict[str, str], action_type: str, **extra):
    body = {
        "action_type": action_type,
        "source_module": extra.pop("source_module", "business"),
        "source_ref_id": extra.pop("source_ref_id", _ref(action_type)),
        "title": extra.pop("title", action_type),
        **extra,
    }
    return client.post("/api/nova/autonomy/intents", headers=headers, json=body)


def _approve(client: TestClient, headers: dict[str, str], audit_id: str, **extra):
    return client.post(f"/api/nova/autonomy/intents/{audit_id}/approve", headers=headers, json=extra)


def test_flag_off_bypasses_autonomy_and_preserves_today(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_AUTONOMY_PHASE1", "0")
    client = _client()
    owner = _login(client)
    blocked = _create(client, owner, "acknowledge")
    assert blocked.status_code == 404
    proposed = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": _ref("v2"),
            "title": "V2 still works",
            "recommended_action": "acknowledge",
        },
    )
    assert proposed.status_code == 200, proposed.text
    acked = client.post(
        f"/api/nova/today/actions/{proposed.json()['action_id']}/approve",
        headers=owner,
        json={},
    )
    assert acked.status_code == 200


def test_low_create_draft_and_task_once_after_owner_approval(monkeypatch) -> None:
    _enable(monkeypatch)
    client = _client()
    owner = _login(client)
    draft_ref = _ref("draft")
    created = _create(
        client,
        owner,
        "create_draft",
        source_module="communications",
        source_ref_id=draft_ref,
        title="Draft follow-up",
    )
    assert created.status_code == 200, created.text
    assert created.json()["risk_class"] == "LOW"
    assert created.json()["executed"] is False
    approved = _approve(
        client,
        owner,
        created.json()["audit_id"],
        draft_to=["pilot@example.com"],
        draft_subject="Re: draft",
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["executed"] is True
    assert approved.json()["result_ref_id"]
    assert approved.json()["verification_result"] == "verified"
    again = _approve(client, owner, created.json()["audit_id"], draft_to=["pilot@example.com"])
    assert again.status_code == 200
    assert again.json()["result_ref_id"] == approved.json()["result_ref_id"]

    task = _create(client, owner, "create_task", source_module="government", source_ref_id=_ref("task"))
    tasked = _approve(client, owner, task.json()["audit_id"], task_title="Phase 1 task")
    assert tasked.status_code == 200, tasked.text
    assert tasked.json()["executed"] is True
    assert tasked.json()["result_ref_id"]
    assert tasked.json()["verification_result"] == "verified"
    tasked_again = _approve(client, owner, task.json()["audit_id"], task_title="Phase 1 task")
    assert tasked_again.json()["result_ref_id"] == tasked.json()["result_ref_id"]


def test_acknowledge_open_link_snooze_dismiss_recheck_history(monkeypatch) -> None:
    _enable(monkeypatch)
    client = _client()
    owner = _login(client)
    ack = _create(client, owner, "acknowledge", source_ref_id=_ref("ack"))
    acked = _approve(client, owner, ack.json()["audit_id"])
    assert acked.status_code == 200, acked.text
    assert acked.json()["verification_result"] == "verified"

    opened = _create(client, owner, "open_link", source_module="link", source_ref_id=_ref("link"))
    opened_out = _approve(client, owner, opened.json()["audit_id"])
    assert opened_out.status_code == 200, opened_out.text
    assert opened_out.json()["executed"] is True

    snooze = _create(client, owner, "snooze", source_ref_id=_ref("snooze"))
    bad = _approve(client, owner, snooze.json()["audit_id"], hours=7)
    assert bad.status_code == 422
    snoozed = _approve(client, owner, snooze.json()["audit_id"], hours=24)
    assert snoozed.status_code == 200, snoozed.text
    assert snoozed.json()["verification_result"] == "verified"

    dismiss = _create(client, owner, "dismiss", source_ref_id=_ref("dismiss"))
    dismissed = _approve(client, owner, dismiss.json()["audit_id"])
    assert dismissed.status_code == 200
    assert dismissed.json()["verification_result"] == "verified"

    recheck = _create(
        client, owner, "recheck_source", source_module="communications", source_ref_id=_ref("recheck")
    )
    checked = _approve(client, owner, recheck.json()["audit_id"])
    assert checked.status_code == 200, checked.text
    assert checked.json()["mutated_external"] is False

    history = _create(client, owner, "history", source_ref_id=_ref("hist"))
    assert history.status_code == 200
    assert history.json()["executed"] is False
    listed = client.get("/api/nova/autonomy/history", headers=owner)
    assert listed.status_code == 200
    assert isinstance(listed.json(), list)


def test_idempotency_key_does_not_duplicate(monkeypatch) -> None:
    _enable(monkeypatch)
    client = _client()
    owner = _login(client)
    headers = {**owner, "Idempotency-Key": "phase1-draft-once"}
    body = {
        "action_type": "create_draft",
        "source_module": "communications",
        "source_ref_id": _ref("idemp"),
        "title": "Idempotent draft",
    }
    first = client.post("/api/nova/autonomy/intents", headers=headers, json=body)
    second = client.post("/api/nova/autonomy/intents", headers=headers, json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["audit_id"] == second.json()["audit_id"]
    approved = _approve(client, owner, first.json()["audit_id"], draft_subject="Once")
    replay = _approve(client, owner, first.json()["audit_id"], draft_subject="Once")
    assert approved.json()["result_ref_id"] == replay.json()["result_ref_id"]


def test_dispatcher_cannot_act_and_cross_org_is_403(monkeypatch) -> None:
    _enable(monkeypatch)
    client = _client()
    owner = _login(client)
    dispatcher = _login(client, "dispatcher@amicor.local")
    created = _create(client, owner, "acknowledge", source_ref_id=_ref("gate"))
    denied = _approve(client, dispatcher, created.json()["audit_id"])
    assert denied.status_code == 403
    cross = client.post(
        "/api/nova/autonomy/intents",
        headers=owner,
        json={
            "action_type": "acknowledge",
            "source_module": "business",
            "source_ref_id": _ref("cross"),
            "organization_id": "org-not-the-caller",
        },
    )
    assert cross.status_code == 403
    cross_act = client.post(
        f"/api/nova/autonomy/intents/{created.json()['audit_id']}/approve",
        headers=owner,
        json={"organization_id": "org-not-the-caller"},
    )
    assert cross_act.status_code == 403


def test_medium_requests_persist_unexecuted(monkeypatch) -> None:
    _enable(monkeypatch)
    client = _client()
    owner = _login(client)
    for action_type in ("send_email", "submit_form", "internal_record_update"):
        created = _create(client, owner, action_type, source_module="communications", source_ref_id=_ref(action_type))
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["risk_class"] == "MEDIUM"
        assert body["approval_state"] == "awaiting_approval"
        assert body["executed"] is False
        approved = _approve(client, owner, body["audit_id"])
        assert approved.status_code == 200
        assert approved.json()["executed"] is False
        assert approved.json()["approval_state"] in {"awaiting_approval", "blocked"}


def test_high_and_prohibited_blocked(monkeypatch) -> None:
    _enable(monkeypatch)
    client = _client()
    owner = _login(client)
    high = _create(client, owner, "payout", source_ref_id=_ref("high"))
    assert high.status_code == 200
    assert high.json()["risk_class"] == "HIGH"
    assert high.json()["approval_state"] == "blocked"
    assert high.json()["executed"] is False
    assert _approve(client, owner, high.json()["audit_id"]).json()["executed"] is False

    prohibited = _create(client, owner, "driver_001", source_ref_id=_ref("proh"))
    assert prohibited.json()["risk_class"] == "PROHIBITED"
    assert prohibited.json()["executed"] is False
    unknown = _create(client, owner, "invent_new_side_effect", source_ref_id=_ref("unk"))
    assert unknown.json()["risk_class"] == "PROHIBITED"


def test_refuses_and_payments_and_routes_and_protected_paths(monkeypatch) -> None:
    _enable(monkeypatch)
    client = _client()
    owner = _login(client)
    dispatcher = _login(client, "dispatcher@amicor.local")
    for path in ("/api/nova/today/send", "/api/nova/today/file", "/api/nova/today/ledger", "/api/nova/today/call"):
        assert client.post(path, headers=owner).status_code == 403
    send = client.post(
        "/api/nova/communications/send",
        headers=owner,
        json={"confirm_send": True, "to": ["a@example.com"], "subject": "no", "body": "no"},
    )
    assert send.status_code == 403
    assert client.get("/api/nova/payments/readiness", headers=dispatcher).status_code == 403
    assert client.get("/api/nova/payments/readiness", headers=owner).status_code == 200
    passed = 0
    for path in NOVA_TABS:
        response = client.get(path, follow_redirects=True)
        assert response.status_code == 200, path
        passed += 1
    assert passed == 13
    for path in AUTONOMY.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            assert all(banned not in module for banned in FORBIDDEN_MODULES), f"{path.name} imports {module}"
    html = (ROOT / "static" / "nova-today" / "today.js").read_text(encoding="utf-8")
    assert "Risk:" in html
    comms = (ROOT / "static" / "nova-communications" / "index.html").read_text(encoding="utf-8")
    assert "awaiting_approval" in comms


def _count_logical(client: TestClient, headers: dict[str, str], module: str, ref: str, action: str) -> int:
    rows = client.get("/api/nova/today/actions", headers=headers).json()
    return sum(
        1
        for row in rows
        if row["source_module"] == module and row["source_ref_id"] == ref and row["recommended_action"] == action
    )


def _seed_today(client: TestClient, headers: dict[str, str], module: str, ref: str, action: str, title: str) -> str:
    created = client.post(
        "/api/nova/today/actions",
        headers=headers,
        json={"source_module": module, "source_ref_id": ref, "title": title, "recommended_action": action},
    )
    assert created.status_code == 200, created.text
    return created.json()["action_id"]


def test_reuses_in_org_logical_row_and_existing_action_id(monkeypatch) -> None:
    _enable(monkeypatch)
    client = _client()
    owner = _login(client)
    dispatcher = _login(client, "dispatcher@amicor.local")
    ref = _ref("shared-ack")
    first = _create(client, owner, "acknowledge", source_module="business", source_ref_id=ref, title="Shared ack")
    second = _create(client, dispatcher, "acknowledge", source_module="business", source_ref_id=ref, title="Shared ack")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["today_action_id"] == second.json()["today_action_id"]
    assert _count_logical(client, owner, "business", ref, "acknowledge") == 1

    existing_id = _seed_today(client, owner, "business", _ref("reuse-id"), "acknowledge", "Reuse supplied id")
    reused = _create(
        client,
        dispatcher,
        "acknowledge",
        source_module="business",
        source_ref_id=_ref("ignored-new-ref"),
        title="Reuse supplied id",
        today_action_id=existing_id,
    )
    assert reused.status_code == 200, reused.text
    assert reused.json()["today_action_id"] == existing_id


def test_standing_synthetic_cards_do_not_duplicate_per_viewer(monkeypatch) -> None:
    _enable(monkeypatch)
    client = _client()
    owner = _login(client)
    dispatcher = _login(client, "dispatcher@amicor.local")
    standing = (
        ("business", "rec-attention", "acknowledge", "Review today's follow-ups and overdue work"),
        ("communications", "rec-drafts", "acknowledge", "Keep replies in drafts"),
        ("link", "health", "open_link", "AMICOR Health"),
        ("link", "delivery", "open_link", "AMICOR Delivery"),
        ("link", "freight", "open_link", "AMICOR Freight"),
    )
    for module, ref, action, title in standing:
        before = _count_logical(client, owner, module, ref, action)
        first = _create(client, owner, action, source_module=module, source_ref_id=ref, title=title)
        if before == 0:
            assert first.status_code == 409, first.text
            seeded = _seed_today(client, dispatcher, module, ref, action, title)
        else:
            assert first.status_code == 200, first.text
            seeded = first.json()["today_action_id"]
        owner_intent = _create(client, owner, action, source_module=module, source_ref_id=ref, title=title)
        disp_intent = _create(client, dispatcher, action, source_module=module, source_ref_id=ref, title=title)
        assert owner_intent.status_code == 200, owner_intent.text
        assert disp_intent.status_code == 200, disp_intent.text
        assert owner_intent.json()["today_action_id"] == seeded
        assert disp_intent.json()["today_action_id"] == seeded
        assert _count_logical(client, owner, module, ref, action) == max(before, 1)


def test_draft_verified_by_same_tenant_admin_and_cross_tenant_denied(monkeypatch) -> None:
    _enable(monkeypatch)
    client = _client()
    owner = _login(client)
    dispatcher = _login(client, "dispatcher@amicor.local")
    ref = _ref("draft-verify")
    proposed = client.post(
        "/api/nova/today/actions",
        headers=dispatcher,
        json={
            "source_module": "communications",
            "source_ref_id": ref,
            "title": "Dispatcher draft",
            "recommended_action": "create_draft",
        },
    )
    assert proposed.status_code == 200, proposed.text
    drafted = client.post(
        f"/api/nova/today/actions/{proposed.json()['action_id']}/approve",
        headers=dispatcher,
        json={"draft_subject": "Tenant draft", "draft_to": ["pilot@example.com"]},
    )
    assert drafted.status_code == 200, drafted.text
    assert drafted.json()["draft_id"]
    assert drafted.json()["verification_status"] == "verified"
    action = drafted.json()["action"]
    assert action["verification_status"] == "verified"
    assert action["verification_label"] != "Draft reference missing"
    as_admin = client.get(
        f"/api/nova/today/actions/{proposed.json()['action_id']}",
        headers=owner,
    )
    assert as_admin.status_code == 200, as_admin.text
    assert as_admin.json()["verification_status"] == "verified"
    assert as_admin.json()["verification_label"] != "Draft reference missing"

    from app.core.nova.today.service import _get_action
    from app.core.nova.today.verify import DraftTenantDenied, verify_draft_by_ref, verify_result
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        login_me = client.get("/api/auth/me", headers=owner)
        assert login_me.status_code == 200
        org_id = login_me.json()["organization_id"]
        from app.auth import UserContext

        admin_ctx = UserContext(
            user_id=login_me.json()["user_id"],
            email=login_me.json()["email"],
            role=login_me.json()["role"],
            organization_id=org_id,
        )
        row = _get_action(db, proposed.json()["action_id"], organization_id=org_id, user=admin_ctx)
        assert verify_result(db, row, organization_id=org_id, user=admin_ctx) == "verified"
        assert verify_draft_by_ref(db, drafted.json()["draft_id"], organization_id=org_id, user=admin_ctx) == "verified"
        try:
            verify_draft_by_ref(
                db, drafted.json()["draft_id"], organization_id="org-not-the-caller", user=admin_ctx
            )
            raise AssertionError("cross-tenant draft lookup should be denied")
        except DraftTenantDenied:
            pass
        assert verify_draft_by_ref(db, None, organization_id=org_id, user=admin_ctx) == "unknown"
