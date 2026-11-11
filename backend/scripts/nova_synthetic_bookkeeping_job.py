"""Run an invented three-part bookkeeping assignment through Nova job logic.

This is a self-contained development simulation. It never uses real customers,
production databases, network services, payment systems or hiring actions.
A synthetic Nova operator performs the work and a simulated owner decision
approves download; no actual person or client gives consent or approval.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import bookkeeping_durable_jobs as finance
from app.core.nova.work_revenue import operations_customer_csv_jobs as durable
from app.core.nova.work_revenue.bookkeeping_assignment import BookkeepingAssignment

OUT = Path(__file__).resolve().parents[1] / "synthetic_out"
ORG = "SYNTHETIC-ORG-01"
OWNER = "SYNTHETIC-OWNER-01"
ENG = "SYNTHETIC-ENGAGEMENT-001"
AS_OF = "2026-11-11"

# Entirely fabricated client data; never substitute bank or BELAY records.
CASES = (
    {
        "task_id": "SIM-TASK-EXPENSES",
        "work_type": "transaction_workpaper",
        "request_id": "synthetic-transaction-001",
        "filename": "synthetic_transaction_review.csv",
        "source": (
            "date,description,amount,reference\n"
            "2026-11-01,Example customer payment,2000.00,R001\n"
            "2026-11-02,Software subscription,-150.00,E001\n"
            "2026-11-03,Office supplies,-35.00,E002\n"
            "2026-11-04,Unknown vendor,-50.00,E003\n"
        ),
        "as_of": None,
        "expected": {"transaction_count": 4, "incoming_total": "2000.00",
                     "outgoing_total": "235.00", "net_total": "1765.00"},
        "required_issue": "category_review",
    },
    {
        "task_id": "SIM-TASK-RECEIVABLES",
        "work_type": "receivables_aging",
        "request_id": "synthetic-receivable-001",
        "filename": "synthetic_receivables_review.csv",
        "source": (
            "invoice_id,customer,invoice_date,due_date,amount,paid\n"
            "INV100,Example Client Alpha,2026-10-01,2026-10-31,1200.00,200.00\n"
            "INV101,Example Client Beta,2026-11-01,2026-11-30,500.00,0.00\n"
            "INV102,Example Client Gamma,2026-07-01,2026-07-31,300.00,100.00\n"
        ),
        "as_of": AS_OF,
        "expected": {"invoice_count": 3, "total_outstanding": "1700.00",
                     "aging_buckets": {"current": "500.00", "1-30": "1000.00",
                                       "31-60": "0.00", "61-90": "0.00", "91+": "200.00"}},
        "required_issue": "verify_payment_allocation",
    },
    {
        "task_id": "SIM-TASK-PAYABLES",
        "work_type": "payables_aging",
        "request_id": "synthetic-payable-001",
        "filename": "synthetic_payables_review.csv",
        "source": (
            "bill_id,vendor,bill_date,due_date,amount,paid\n"
            "BILL200,Example Vendor North,2026-10-01,2026-11-01,600.00,100.00\n"
            "BILL201,Example Vendor West,2026-11-01,2026-11-15,250.00,0.00\n"
            "BILL202,Example Vendor East,2026-11-01,2026-12-05,75.00,0.00\n"
        ),
        "as_of": AS_OF,
        "expected": {"bill_count": 3, "total_unpaid": "825.00",
                     "due_buckets": {"overdue": "500.00", "due_0_7": "250.00",
                                     "due_8_30": "75.00", "due_later": "0.00"}},
        "required_issue": "verify_payment_allocation",
    },
)


class SimulatedPrivateStorage:
    """In-memory-only private object store, never an S3/Render validation."""
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def store(self, *, organization_id, application_id, category,
              filename, content_type, stream):
        assert organization_id == ORG
        assert category == "nova-bookkeeping-review"
        assert content_type == "text/csv"
        ref = "/".join((organization_id, application_id, category, filename))
        body = stream.read()
        self.objects[ref] = body
        return "SYNTHETIC_ONLY", ref, len(body)

    def retrieve(self, *, storage_ref):
        return self.objects[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        del self.objects[storage_ref]


def execute() -> dict:
    """Produce three simulated owner-reviewed workpapers and auditable manifest."""
    OUT.mkdir(parents=True, exist_ok=True)
    store = SimulatedPrivateStorage()
    engine = create_engine("sqlite:///:memory:")
    durable.metadata.create_all(engine)
    summary = {
        "case_id": ENG,
        "client": "Invented demo client (not BELAY)",
        "operator": "SIMULATED_NOVA_OPERATIONS_AGENT",
        "owner_review": "SIMULATED_OWNER_APPROVAL_ONLY",
        "environment": "IN_MEMORY_SQLITE_AND_FAKE_PRIVATE_STORAGE",
        "customer_data_used": False,
        "paid_work": False,
        "contract_signed": False,
        "client_delivery_performed": False,
        "as_of": AS_OF,
        "jobs": [],
    }
    try:
        with patch.dict(os.environ, {"NOVA_BOOKKEEPING_DURABLE_ENABLED": "true"}), \
             patch.object(durable, "require_runtime", lambda db: None), \
             patch.object(durable, "_store", lambda: store), \
             Session(engine) as db:
            for case in CASES:
                assignment = BookkeepingAssignment(
                    organization_id=ORG, owner_user_id=OWNER,
                    engagement_id=ENG, task_id=case["task_id"],
                    work_type=case["work_type"],
                    ai_assistance_permitted=True,
                    data_processing_authorized=True,
                    human_review_required=True,
                    contracted_work_types=frozenset({case["work_type"]}),
                )
                # These booleans represent invented test permissions, not
                # evidence of a real customer's authorization.
                raw = case["source"].encode("utf-8")
                job = finance.submit_bookkeeping_review(
                    db, assignment=assignment, request_id=case["request_id"],
                    primary=raw, as_of=case["as_of"],
                )
                assert job["status"] == "AWAITING_REVIEW"
                assert not job["delivered"]
                repeat = finance.submit_bookkeeping_review(
                    db, assignment=assignment, request_id=case["request_id"],
                    primary=raw, as_of=case["as_of"],
                )
                assert repeat["replayed"] and repeat["job_id"] == job["job_id"]
                # An unauthorized owner cannot retrieve the workpaper.
                try:
                    finance.download_bookkeeping(
                        db, org=ORG, owner="OTHER-SYNTHETIC-OWNER",
                        job_id=job["job_id"],
                    )
                except durable.CustomerCSVBlocked:
                    pass
                else:
                    raise AssertionError("Cross-owner download was not denied")

                output = finance.download_bookkeeping(
                    db, org=ORG, owner=OWNER, job_id=job["job_id"],
                )
                assert hashlib.sha256(output).hexdigest() == job["output_sha256"]
                # Compare actual processing results against independently
                # specified scenario numbers, not merely successful execution.
                from app.core.nova.work_revenue.bookkeeping_assignment import prepare_assignment_draft
                draft = prepare_assignment_draft(
                    assignment, primary_csv=case["source"], as_of=case["as_of"],
                )["draft"]
                for field, expected in case["expected"].items():
                    assert draft[field] == expected, (case["task_id"], field, draft[field])
                assert draft["issue_counts"].get(case["required_issue"], 0) >= 1
                assert draft["status"] == "DRAFT_FOR_HUMAN_REVIEW"
                approval = finance.review_bookkeeping(
                    db, org=ORG, owner=OWNER, job_id=job["job_id"], approve=True,
                )
                assert approval["status"] == "APPROVED_FOR_DOWNLOAD"
                assert approval["delivered"] is False
                assert finance.download_bookkeeping(
                    db, org=ORG, owner=OWNER, job_id=job["job_id"],
                ) == output
                (OUT / case["filename"]).write_bytes(output)
                summary["jobs"].append({
                    "task_id": case["task_id"],
                    "work_type": case["work_type"],
                    "status": approval["status"],
                    "simulated_owner_review": True,
                    "delivered": False,
                    "source_rows": len(case["source"].strip().splitlines()) - 1,
                    "output_file": case["filename"],
                    "output_sha256": job["output_sha256"],
                    "provenance_scope_sha256": job["provenance"]["scope_sha256"],
                    "expected_figures": case["expected"],
                    "exception_counts": draft["issue_counts"],
                    "idempotent_replay_verified": True,
                    "cross_owner_download_blocked": True,
                })
    finally:
        engine.dispose()
    assert len(summary["jobs"]) == len(CASES) == 3
    summary["synthetic_jobs_completed"] = len(summary["jobs"])
    summary["release_ready"] = False
    (OUT / "synthetic_assignment_report.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    result = execute()
    print(json.dumps({
        "case_id": result["case_id"],
        "simulated_jobs": result["synthetic_jobs_completed"],
        "approved_for_owner_download_only": True,
        "client_delivery": False,
        "release_ready": False,
        "output": str(OUT),
    }, sort_keys=True))
