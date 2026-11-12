"""Synthetic accounts payable workpaper regression tests."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "app/core/nova/work_revenue/bookkeeping_payables.py"
SPEC = importlib.util.spec_from_file_location("isolated_nova_payables", PATH)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
HEAD = "bill_id,vendor,bill_date,due_date,amount,paid\n"


class PayablesWorkpaperTests(unittest.TestCase):
    def test_due_buckets_and_partial_payments(self):
        raw = HEAD + (
            "B1,Vendor A,2026-10-01,2026-11-01,100.00,25.00\n"
            "B2,Vendor B,2026-11-01,2026-11-15,40.00,0\n"
            "B3,Vendor C,2026-11-01,2026-12-10,30.00,0\n"
            "B4,Vendor D,2026-11-01,2026-11-25,50.00,0\n"
        )
        result = MOD.build_payables_workpaper(raw, as_of="2026-11-11")
        self.assertEqual(result["total_unpaid"], "195.00")
        self.assertEqual(result["due_buckets"], {
            "overdue": "75.00", "due_0_7": "40.00",
            "due_8_30": "80.00", "due_later": "0.00",
        })
        self.assertFalse(result["payment_authorized"])
        self.assertEqual(result["issue_counts"]["verify_payment_allocation"], 1)

    def test_duplicate_and_future_bill_flags(self):
        raw = HEAD + "X1,Vendor,2026-11-15,2026-12-01,10.00,0\n" * 2
        result = MOD.build_payables_workpaper(raw, as_of="2026-11-11")
        self.assertEqual(result["issue_counts"]["duplicate_bill_id"], 2)
        self.assertEqual(result["issue_counts"]["future_dated_bill"], 2)

    def test_invalid_amounts_rejected(self):
        for amount, paid in (("NaN", "0"), ("10.001", "0"), ("10", "-1"), ("5", "6")):
            with self.subTest(amount=amount, paid=paid):
                with self.assertRaises(MOD.PayablesInputError):
                    MOD.build_payables_workpaper(
                        HEAD + f"B1,Vendor,2026-11-01,2026-11-20,{amount},{paid}\n",
                        as_of="2026-11-11",
                    )

    def test_formula_escape(self):
        raw = HEAD + 'B1,"=HYPERLINK(""unsafe"")",2026-11-01,2026-11-20,20,0\n'
        self.assertIn(
            "'=HYPERLINK",
            MOD.build_payables_workpaper(raw, as_of="2026-11-11")["workpaper_csv"],
        )

    def test_dates_and_empty(self):
        with self.assertRaises(MOD.PayablesInputError):
            MOD.build_payables_workpaper(
                HEAD + "B1,Vendor,2026-11-20,2026-11-01,20,0\n",
                as_of="2026-11-11",
            )
        result = MOD.build_payables_workpaper(HEAD, as_of="2026-11-11")
        self.assertEqual(result["status"], "DRAFT_FOR_HUMAN_REVIEW")
        self.assertEqual(result["total_unpaid"], "0.00")


if __name__ == "__main__":
    unittest.main()
