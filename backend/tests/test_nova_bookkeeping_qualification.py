"""Contract scope controls: synthetic descriptions only."""
import unittest

from app.core.nova.v3.capability_catalog import capability_fit


class NovaBookkeepingQualificationTests(unittest.TestCase):
    def test_expense_cleanup_is_in_scope_as_candidate_only(self):
        result = capability_fit(
            "Expense categorization and receipt organization in a financial spreadsheet",
            title="Expense data cleanup project",
        )
        self.assertTrue(result["fit"])
        self.assertIn("bookkeeping_support", [c["capability_id"] for c in result["capabilities"]])

    def test_full_cycle_bookkeeping_is_not_qualified(self):
        result = capability_fit(
            "Bookkeeping support plus full-cycle bookkeeping and month-end close",
            title="Bookkeeper",
        )
        self.assertFalse(result["fit"])
        self.assertIn("unsupported_financial_scope", result["blockers"])

    def test_payroll_or_tax_work_is_not_qualified(self):
        for scope in ("payroll processing", "prepare tax returns", "1099 filing"):
            with self.subTest(scope=scope):
                result = capability_fit("Bookkeeping support and " + scope, title="Bookkeeper")
                self.assertFalse(result["fit"])

    def test_personally_performed_role_is_blocked(self):
        result = capability_fit(
            "Bookkeeping support; must personally perform all work",
            title="Bookkeeper",
        )
        self.assertFalse(result["fit"])
        self.assertIn("human_only_work", result["blockers"])


if __name__ == "__main__":
    unittest.main()
