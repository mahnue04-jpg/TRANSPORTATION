"""Synthetic only: accounting workpaper calculations never contact clients."""
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "app/core/nova/work_revenue/bookkeeping_receivables.py"
SPEC = importlib.util.spec_from_file_location("nova_ar_isolated", MODULE)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

HEAD = "invoice_id,customer,invoice_date,due_date,amount,paid\n"

class ReceivablesTests(unittest.TestCase):
    def test_aging_and_partially_paid(self):
        data = HEAD + (
            "A01,Example Ltd,2026-10-01,2026-10-31,100.00,25.00\n"
            "A02,Other Ltd,2026-11-01,2026-11-30,80.00,0.00\n"
            "A03,Third Ltd,2026-08-01,2026-08-31,50.00,0.00\n"
        )
        out = mod.build_receivables_aging(data, as_of="2026-11-11")
        self.assertEqual(out["total_outstanding"], "205.00")
        self.assertEqual(out["aging_buckets"]["1-30"], "75.00")
        self.assertEqual(out["aging_buckets"]["current"], "80.00")
        self.assertEqual(out["aging_buckets"]["61-90"], "50.00")
        self.assertEqual(out["issue_counts"]["verify_payment_allocation"], 1)
        self.assertIn("NEEDS_HUMAN_REVIEW", out["workpaper_csv"])

    def test_duplicate_and_future_dated_invoice(self):
        data = HEAD + "A1,Client,2026-11-12,2026-11-30,25.00,0\n" * 2
        out = mod.build_receivables_aging(data, as_of="2026-11-11")
        self.assertEqual(out["issue_counts"]["duplicate_invoice_id"], 2)
        self.assertEqual(out["issue_counts"]["future_dated_invoice"], 2)

    def test_reject_bad_payment_dates(self):
        for row in (
            "A1,Client,2026-11-01,2026-11-30,10,11\n",
            "A1,Client,2026-11-01,2026-11-30,10,-1\n",
            "A1,Client,2026-11-30,2026-11-01,10,0\n",
            "A1,Client,2026-11-01,2026-11-30,NaN,0\n",
            "A1,Client,2026-11-01,2026-11-30,10.001,0\n",
        ):
            with self.subTest(row=row):
                with self.assertRaises(mod.ReceivableInputError):
                    mod.build_receivables_aging(HEAD + row, as_of="2026-11-11")

    def test_csv_formula_escape(self):
        data = HEAD + 'A1,"=HYPERLINK(""unsafe"")",2026-11-01,2026-11-30,100,0\n'
        out = mod.build_receivables_aging(data, as_of="2026-11-11")
        self.assertIn("'=HYPERLINK", out["workpaper_csv"])

    def test_header_and_date_validation(self):
        with self.assertRaises(mod.ReceivableInputError):
            mod.build_receivables_aging("wrong,columns\n", as_of="2026-11-11")
        with self.assertRaises(mod.ReceivableInputError):
            mod.build_receivables_aging(HEAD, as_of="20261111")

    def test_empty_is_draft(self):
        out = mod.build_receivables_aging(HEAD, as_of="2026-11-11")
        self.assertEqual(out["invoice_count"], 0)
        self.assertEqual(out["status"], "DRAFT_FOR_HUMAN_REVIEW")

if __name__ == "__main__":
    unittest.main()
