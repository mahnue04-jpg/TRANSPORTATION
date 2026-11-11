"""No real customer records used in bookkeeping workpaper tests."""
import unittest

from app.core.nova.work_revenue.bookkeeping_workpaper import (
    BookkeepingInputError,
    build_bookkeeping_workpaper,
)

HEAD = "date,description,amount,reference\n"


class BookkeepingWorkpaperTests(unittest.TestCase):
    def test_amounts_review_and_exact_bank_match(self):
        transactions = HEAD + (
            "2026-11-01,Software subscription,-25.00,A1\n"
            "2026-11-02,Client payment,150.00,B2\n"
        )
        bank = HEAD + (
            "2026-11-01,Subscription debit,-25.00,A1\n"
            "2026-11-02,Deposit,150.00,B2\n"
        )
        report = build_bookkeeping_workpaper(transactions, bank)
        self.assertEqual(report["status"], "DRAFT_FOR_HUMAN_REVIEW")
        self.assertEqual(report["incoming_total"], "150.00")
        self.assertEqual(report["outgoing_total"], "25.00")
        self.assertEqual(report["net_total"], "125.00")
        self.assertEqual(report["unmatched_bank_rows"], [])
        self.assertIn("Software subscriptions", report["workpaper_csv"])
        self.assertIn(",-25.00,", report["workpaper_csv"])
        self.assertEqual(report["matched_bank_row_count"], 2)
        self.assertTrue(report["all_bank_rows_accounted_for"])
        self.assertIn("NEEDS_HUMAN_REVIEW", report["workpaper_csv"])

    def test_duplicate_and_missing_bank_flagged(self):
        data = HEAD + "2026-11-01,Office supplies,-12.00,X\n" * 2
        report = build_bookkeeping_workpaper(data, HEAD)
        self.assertEqual(report["issue_counts"]["possible_duplicate"], 2)
        self.assertEqual(report["issue_counts"]["bank_match_missing_or_ambiguous"], 2)

    def test_duplicate_transactions_never_claim_a_unique_bank_match(self):
        transactions = HEAD + "2026-11-01,Software subscription,-25.00,A1\\n" * 2
        bank = HEAD + "2026-11-01,Bank charge,-25.00,A1\\n"
        report = build_bookkeeping_workpaper(transactions, bank)
        self.assertEqual(report["issue_counts"]["bank_match_missing_or_ambiguous"], 2)
        self.assertEqual(report["matched_bank_row_count"], 0)
        self.assertEqual(report["unmatched_bank_rows"], [2])
        self.assertFalse(report["all_bank_rows_accounted_for"])

    def test_csv_injection_is_escaped(self):
        data = HEAD + '2026-11-01,"=HYPERLINK(""bad"")",10.00,AB\n'
        report = build_bookkeeping_workpaper(data)
        self.assertIn("'=HYPERLINK", report["workpaper_csv"])

    def test_invalid_amounts_and_dates_rejected(self):
        for value in ("NaN", "Infinity", "12.001", "hello"):
            with self.subTest(value=value):
                with self.assertRaises(BookkeepingInputError):
                    build_bookkeeping_workpaper(HEAD + f"2026-11-01,Item,{value},X\n")
        with self.assertRaises(BookkeepingInputError):
            build_bookkeeping_workpaper(HEAD + "2026-02-30,Item,2.00,X\n")

    def test_missing_reference_is_not_auto_matched(self):
        data = HEAD + "2026-11-01,Item,2.00,\n"
        report = build_bookkeeping_workpaper(data, data)
        self.assertEqual(report["unmatched_bank_rows"], [2])
        self.assertEqual(report["issue_counts"]["bank_match_missing_or_ambiguous"], 1)

    def test_reject_malformed_csv(self):
        with self.assertRaises(BookkeepingInputError):
            build_bookkeeping_workpaper("date,description,amount,reference\n2026-11-01,Item,3\n")
        with self.assertRaises(BookkeepingInputError):
            build_bookkeeping_workpaper("date,date,amount,reference\n")

    def test_size_limit(self):
        with self.assertRaises(BookkeepingInputError):
            build_bookkeeping_workpaper(HEAD + "a" * 1_000_001)

    def test_empty_report_is_not_considered_completed_work(self):
        report = build_bookkeeping_workpaper(HEAD)
        self.assertEqual(report["transaction_count"], 0)
        self.assertEqual(report["status"], "DRAFT_FOR_HUMAN_REVIEW")


if __name__ == "__main__":
    unittest.main()
