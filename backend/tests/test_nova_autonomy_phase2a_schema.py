"""Phase 2A schema/models only. No APIs, worker, or Phase 2 flag."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.auth import UserContext
from app.core.nova.autonomy.ledger import append, ensure_autonomy_schema
from app.core.nova.autonomy.models import (
    NovaAutonomyApproval,
    NovaAutonomyExecutionAttempt,
    NovaAutonomyLedger,
    NovaAutonomyOrgFlag,
    NovaAutonomyWorkflow,
    NovaAutonomyWorkflowStep,
    new_approval_id,
    new_attempt_id,
    new_step_id,
    new_workflow_id,
)
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import now, uuid4

PHASE2_TABLES = {
    "nova_autonomy_workflows",
    "nova_autonomy_workflow_steps",
    "nova_autonomy_approvals",
    "nova_autonomy_execution_attempts",
    "nova_autonomy_org_flags",
}


def _org() -> str:
    return "org-p2a-" + uuid4()[:12]


def _setup() -> None:
    init_platform_db()
    ensure_autonomy_schema(engine)


def _workflow(organization_id: str, **extra) -> NovaAutonomyWorkflow:
    return NovaAutonomyWorkflow(
        workflow_id=extra.pop("workflow_id", new_workflow_id()),
        organization_id=organization_id,
        owner_user_id=extra.pop("owner_user_id", "owner-" + uuid4()[:8]),
        correlation_id=extra.pop("correlation_id", "corr-" + uuid4()[:12]),
        workflow_type=extra.pop("workflow_type", "research_draft_task"),
        initiating_module=extra.pop("initiating_module", "today"),
        source_ref_id=extra.pop("source_ref_id", "p2a-source"),
        status=extra.pop("status", "proposed"),
        **extra,
    )


def _step(workflow: NovaAutonomyWorkflow, sequence_number: int, **extra) -> NovaAutonomyWorkflowStep:
    return NovaAutonomyWorkflowStep(
        step_id=extra.pop("step_id", new_step_id()),
        workflow_id=workflow.workflow_id,
        organization_id=workflow.organization_id,
        sequence_number=sequence_number,
        source_module=extra.pop("source_module", "today"),
        target_module=extra.pop("target_module", "communications"),
        action_type=extra.pop("action_type", "create_draft"),
        risk_class=extra.pop("risk_class", "LOW"),
        idempotency_key=extra.pop("idempotency_key", f"{workflow.workflow_id}-step-{sequence_number}"),
        **extra,
    )


def test_phase2a_tables_and_ledger_columns_exist() -> None:
    _setup()
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    assert "nova_autonomy_ledger" in names
    assert PHASE2_TABLES.issubset(names)
    ledger_cols = {col["name"] for col in inspector.get_columns("nova_autonomy_ledger")}
    assert {
        "audit_id",
        "correlation_id",
        "organization_id",
        "action_type",
        "workflow_id",
        "step_id",
        "target_module",
        "approver_user_id",
        "attempt_number",
    }.issubset(ledger_cols)


def test_model_creation_and_required_organization_scope() -> None:
    _setup()
    org = _org()
    with SessionLocal() as db:
        workflow = _workflow(org)
        db.add(workflow)
        db.commit()
        loaded = db.get(NovaAutonomyWorkflow, workflow.workflow_id)
        assert loaded is not None
        assert loaded.organization_id == org
        assert loaded.status == "proposed"
        db.add(_workflow(None))  # type: ignore[arg-type]
        with pytest.raises(IntegrityError):
            db.commit()


def test_workflow_step_relationship_and_deterministic_order() -> None:
    _setup()
    org = _org()
    with SessionLocal() as db:
        workflow = _workflow(org, correlation_id="keep-correlation")
        db.add(workflow)
        db.flush()
        db.add(_step(workflow, 3, action_type="create_task", target_module="business"))
        db.add(_step(workflow, 1, action_type="recheck_source", target_module="today"))
        db.add(_step(workflow, 2, action_type="create_draft", target_module="communications"))
        db.commit()
        ordered = (
            db.query(NovaAutonomyWorkflowStep)
            .filter(
                NovaAutonomyWorkflowStep.organization_id == org,
                NovaAutonomyWorkflowStep.workflow_id == workflow.workflow_id,
            )
            .order_by(NovaAutonomyWorkflowStep.sequence_number.asc())
            .all()
        )
        assert [row.sequence_number for row in ordered] == [1, 2, 3]
        assert [row.action_type for row in ordered] == ["recheck_source", "create_draft", "create_task"]
        assert all(row.organization_id == org for row in ordered)
        assert all(row.workflow_id == workflow.workflow_id for row in ordered)
        assert db.get(NovaAutonomyWorkflow, workflow.workflow_id).correlation_id == "keep-correlation"


def test_unique_idempotency_rejects_duplicate_execution_intent() -> None:
    _setup()
    org = _org()
    with SessionLocal() as db:
        workflow = _workflow(org)
        db.add(workflow)
        db.flush()
        db.add(_step(workflow, 1, idempotency_key="p2a-once"))
        db.commit()
        db.add(_step(workflow, 2, idempotency_key="p2a-once"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_duplicate_step_sequence_rejected() -> None:
    _setup()
    org = _org()
    with SessionLocal() as db:
        workflow = _workflow(org)
        db.add(workflow)
        db.flush()
        db.add(_step(workflow, 1, idempotency_key="p2a-seq-a"))
        db.commit()
        db.add(_step(workflow, 1, idempotency_key="p2a-seq-b"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_approval_expiry_and_revocation_fields() -> None:
    _setup()
    org = _org()
    stamp = now()
    with SessionLocal() as db:
        workflow = _workflow(org)
        db.add(workflow)
        db.flush()
        step = _step(workflow, 1)
        db.add(step)
        db.flush()
        approval = NovaAutonomyApproval(
            approval_id=new_approval_id(),
            workflow_id=workflow.workflow_id,
            step_id=step.step_id,
            organization_id=org,
            approver_user_id="admin-user",
            approval_scope="step",
            status="granted",
            expires_at=stamp + timedelta(hours=4),
        )
        db.add(approval)
        db.commit()
        loaded = db.get(NovaAutonomyApproval, approval.approval_id)
        assert loaded.expires_at is not None
        assert loaded.revoked_at is None
        assert loaded.organization_id == org
        loaded.status = "revoked"
        loaded.revoked_at = stamp
        db.commit()
        again = db.get(NovaAutonomyApproval, approval.approval_id)
        assert again.status == "revoked"
        assert again.revoked_at is not None
        assert again.expires_at is not None


def test_execution_attempts_are_append_only_history() -> None:
    _setup()
    org = _org()
    with SessionLocal() as db:
        workflow = _workflow(org)
        db.add(workflow)
        db.flush()
        step = _step(workflow, 1)
        db.add(step)
        db.flush()
        first = NovaAutonomyExecutionAttempt(
            attempt_id=new_attempt_id(),
            workflow_id=workflow.workflow_id,
            step_id=step.step_id,
            organization_id=org,
            attempt_number=1,
            executed=False,
            failure_reason="transient",
        )
        db.add(first)
        db.commit()
        first_id = first.attempt_id
        db.add(
            NovaAutonomyExecutionAttempt(
                attempt_id=new_attempt_id(),
                workflow_id=workflow.workflow_id,
                step_id=step.step_id,
                organization_id=org,
                attempt_number=2,
                executed=False,
                verification_status="unknown",
            )
        )
        db.commit()
        rows = (
            db.query(NovaAutonomyExecutionAttempt)
            .filter(NovaAutonomyExecutionAttempt.organization_id == org)
            .order_by(NovaAutonomyExecutionAttempt.attempt_number.asc())
            .all()
        )
        assert len(rows) == 2
        assert rows[0].attempt_id == first_id
        assert rows[0].failure_reason == "transient"
        assert rows[1].attempt_number == 2
        db.add(
            NovaAutonomyExecutionAttempt(
                attempt_id=new_attempt_id(),
                workflow_id=workflow.workflow_id,
                step_id=step.step_id,
                organization_id=org,
                attempt_number=1,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_org_flag_defaults_off_and_emergency_stop_false() -> None:
    _setup()
    org = _org()
    with SessionLocal() as db:
        db.add(NovaAutonomyOrgFlag(organization_id=org))
        db.commit()
        flag = db.get(NovaAutonomyOrgFlag, org)
        assert flag.phase2_enabled is False
        assert flag.emergency_stop is False
        assert flag.disabled_at is None
        assert flag.disabled_by is None


def test_cross_org_lookup_isolation() -> None:
    _setup()
    org_a = _org()
    org_b = _org()
    with SessionLocal() as db:
        left = _workflow(org_a, source_ref_id="left")
        right = _workflow(org_b, source_ref_id="right")
        db.add_all([left, right])
        db.flush()
        db.add(_step(left, 1, idempotency_key="iso-a"))
        db.add(_step(right, 1, idempotency_key="iso-b"))
        db.commit()
        visible = (
            db.query(NovaAutonomyWorkflow)
            .filter(NovaAutonomyWorkflow.organization_id == org_a)
            .all()
        )
        assert [row.workflow_id for row in visible] == [left.workflow_id]
        hidden_steps = (
            db.query(NovaAutonomyWorkflowStep)
            .filter(NovaAutonomyWorkflowStep.organization_id == org_a)
            .all()
        )
        assert all(row.workflow_id == left.workflow_id for row in hidden_steps)
        assert db.get(NovaAutonomyWorkflow, right.workflow_id).organization_id == org_b


def test_restrict_delete_does_not_erase_steps_or_ledger() -> None:
    _setup()
    org = _org()
    user = UserContext(user_id="u1", email="admin@amicor.local", role="admin", organization_id=org)
    with SessionLocal() as db:
        workflow = _workflow(org)
        db.add(workflow)
        db.flush()
        db.add(_step(workflow, 1))
        db.commit()
        append(
            db,
            user=user,
            organization_id=org,
            action_type="create_draft",
            risk_class="LOW",
            approval_state="awaiting_approval",
            source_module="communications",
            source_ref_id="p2a-ledger",
            workflow_id=workflow.workflow_id,
        )
        db.delete(db.get(NovaAutonomyWorkflow, workflow.workflow_id))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.get(NovaAutonomyWorkflow, workflow.workflow_id) is not None
        assert (
            db.query(NovaAutonomyLedger)
            .filter(NovaAutonomyLedger.organization_id == org, NovaAutonomyLedger.workflow_id == workflow.workflow_id)
            .count()
            == 1
        )


def test_phase1_ledger_append_still_works_without_phase2_fields() -> None:
    _setup()
    org = _org()
    user = UserContext(user_id="u1", email="admin@amicor.local", role="admin", organization_id=org)
    with SessionLocal() as db:
        row = append(
            db,
            user=user,
            organization_id=org,
            action_type="acknowledge",
            risk_class="LOW",
            approval_state="awaiting_approval",
            source_module="business",
            source_ref_id="p2a-phase1",
        )
        assert row.audit_id.startswith("NAL-")
        assert row.workflow_id is None
        assert row.step_id is None
        assert row.attempt_number is None
        assert row.executed is False


def test_additive_columns_preserve_existing_phase1_row() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / f"p2a_additive_{uuid4()[:8]}.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    local = create_engine(f"sqlite:///{path}")
    with local.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE nova_autonomy_ledger (
                    id VARCHAR(36) PRIMARY KEY,
                    audit_id VARCHAR(40) NOT NULL,
                    correlation_id VARCHAR(80) NOT NULL,
                    idempotency_key VARCHAR(80),
                    actor_user_id VARCHAR(36) NOT NULL,
                    actor_role VARCHAR(40) NOT NULL,
                    organization_id VARCHAR(36) NOT NULL,
                    action_type VARCHAR(64) NOT NULL,
                    source_module VARCHAR(40) NOT NULL,
                    source_ref_id VARCHAR(80) NOT NULL,
                    result_ref_id VARCHAR(80),
                    target VARCHAR(240),
                    risk_class VARCHAR(16) NOT NULL,
                    approval_state VARCHAR(32) NOT NULL,
                    executed BOOLEAN NOT NULL,
                    today_action_id VARCHAR(32),
                    result VARCHAR(240) NOT NULL,
                    verification_result VARCHAR(40),
                    detail TEXT,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO nova_autonomy_ledger (
                    id, audit_id, correlation_id, actor_user_id, actor_role, organization_id,
                    action_type, source_module, source_ref_id, risk_class, approval_state,
                    executed, result, created_at
                ) VALUES (
                    'keep-1', 'NAL-KEEP00000001', 'corr-keep', 'u1', 'admin', 'org-keep',
                    'acknowledge', 'business', 'legacy-row', 'LOW', 'awaiting_approval',
                    0, 'intent_created', '2026-09-13 00:00:00'
                )
                """
            )
        )
    ensure_autonomy_schema(local)
    ensure_autonomy_schema(local)
    inspector = inspect(local)
    cols = {col["name"] for col in inspector.get_columns("nova_autonomy_ledger")}
    assert {"workflow_id", "step_id", "target_module", "approver_user_id", "attempt_number"}.issubset(cols)
    assert PHASE2_TABLES.issubset(set(inspector.get_table_names()))
    Session = sessionmaker(bind=local)
    with Session() as db:
        row = db.get(NovaAutonomyLedger, "keep-1")
        assert row is not None
        assert row.audit_id == "NAL-KEEP00000001"
        assert row.action_type == "acknowledge"
        assert row.workflow_id is None
        assert db.query(NovaAutonomyLedger).count() == 1
