"""Contract scope tests: only synthetic fixture data is processed."""
import importlib.util
import hashlib
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "app/core/nova/work_revenue"
PKG = "isolated_nova_bookkeeping"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg
for module in ("bookkeeping_workpaper", "bookkeeping_receivables", "bookkeeping_payables", "bookkeeping_assignment"):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{module}", ROOT / f"{module}.py")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
from isolated_nova_bookkeeping.bookkeeping_assignment import (
    AssignmentNotAuthorized, BookkeepingAssignment, prepare_assignment_draft,
)

class ContractScopeTests(unittest.TestCase):
    def approved(self, **kwargs):
        data = dict(
            organization_id="org-a", owner_user_id="owner-a",
            engagement_id="eng-a", task_id="task-a",
            work_type="receivables_aging",
            ai_assistance_permitted=True, data_processing_authorized=True,
            human_review_required=True,
            contracted_work_types=frozenset({"receivables_aging"}),
        )
        data.update(kwargs)
        return BookkeepingAssignment(**data)

    def test_review_only_output(self):
        result = prepare_assignment_draft(
            self.approved(),
            primary_csv="invoice_id,customer,invoice_date,due_date,amount,paid\n"
                        "X1,Test Customer,2026-10-01,2026-10-31,100.00,0\n",
            as_of="2026-11-11",
        )
        self.assertEqual(result["status"], "AWAITING_HUMAN_REVIEW")
        self.assertFalse(result["delivery_allowed"])
        self.assertFalse(result["financial_execution"])
        self.assertEqual(result["draft"]["total_outstanding"], "100.00")
        self.assertEqual(result["provenance"]["output_sha256"], hashlib.sha256(result["draft"]["workpaper_csv"].encode("utf-8")).hexdigest())
        self.assertEqual(len(result["provenance"]["scope_sha256"]), 64)
        self.assertFalse(result["provenance"]["delivery_allowed"])

    def test_refuses_unauthorized_work(self):
        changes = [
            dict(ai_assistance_permitted=False),
            dict(data_processing_authorized=False),
            dict(human_review_required=False),
            dict(contracted_work_types=frozenset({"transaction_workpaper"})),
            dict(contracted_work_types=frozenset({"receivables_aging", "payroll"})),
            dict(work_type="payroll", contracted_work_types=frozenset({"payroll"})),
            dict(organization_id=""),
        ]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(AssignmentNotAuthorized):
                    prepare_assignment_draft(self.approved(**change), primary_csv="anything", as_of="2026-11-11")

    def test_transaction_route(self):
        result = prepare_assignment_draft(
            self.approved(work_type="transaction_workpaper", contracted_work_types=frozenset({"transaction_workpaper"})),
            primary_csv="date,description,amount,reference\n2026-11-01,Office supplies,-10.00,X1\n",
        )
        self.assertEqual(result["draft"]["outgoing_total"], "10.00")
        self.assertEqual(result["status"], "AWAITING_HUMAN_REVIEW")

    def test_provenance_is_bound_to_tenant_and_task(self):
        csv_text = "date,description,amount,reference\\n2026-11-01,Office supplies,-10.00,X1\\n"
        common = dict(work_type="transaction_workpaper", contracted_work_types=frozenset({"transaction_workpaper"}))
        one = prepare_assignment_draft(self.approved(**common), primary_csv=csv_text)
        two = prepare_assignment_draft(self.approved(**dict(common, task_id="task-b")), primary_csv=csv_text)
        self.assertEqual(one["provenance"]["output_sha256"], two["provenance"]["output_sha256"])
        self.assertNotEqual(one["provenance"]["scope_sha256"], two["provenance"]["scope_sha256"])

    def test_payables_route_uses_explicit_contract_scope(self):
        result = prepare_assignment_draft(
            self.approved(work_type="payables_aging", contracted_work_types=frozenset({"payables_aging"})),
            primary_csv="bill_id,vendor,bill_date,due_date,amount,paid\\nB1,Test Vendor,2026-11-01,2026-11-10,50,10\\n",
            as_of="2026-11-11",
        )
        self.assertEqual(result["status"], "AWAITING_HUMAN_REVIEW")
        self.assertEqual(result["draft"]["total_unpaid"], "40.00")
        self.assertFalse(result["delivery_allowed"])

    def test_rejects_wrong_shape(self):
        with self.assertRaises(AssignmentNotAuthorized):
            prepare_assignment_draft(self.approved(), primary_csv="x", as_of=None)
        with self.assertRaises(AssignmentNotAuthorized):
            prepare_assignment_draft(self.approved(), primary_csv="x", secondary_csv="x", as_of="2026-11-11")

if __name__ == "__main__":
    unittest.main()
