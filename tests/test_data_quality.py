"""Tests for FMP data quality detection — zero-filled statements and FCF exclusion."""
import unittest
from edenfintech_scanner_bootstrap.fmp import (
    _check_statement_completeness,
    _fcf_margin_history_pct,
    _revenue_history_billions,
)


class TestStatementCompleteness(unittest.TestCase):
    """Tests for _check_statement_completeness."""

    def test_zero_filled_cashflow_detected(self):
        """CF with all zeros + positive cash → warning."""
        cash_flows = [{
            "date": "2025-03-31",
            "operatingCashFlow": 0,
            "capitalExpenditure": 0,
            "freeCashFlow": 0,
            "cashAtEndOfPeriod": 282_000_000,
        }]
        result = _check_statement_completeness([], cash_flows, [])
        self.assertTrue(result["has_incomplete_statements"])
        self.assertIn("2025", result["incomplete_years"])
        self.assertEqual(result["warnings"][0]["statement"], "cash_flow")

    def test_normal_cashflow_not_flagged(self):
        """Normal CF → no warning."""
        cash_flows = [{
            "date": "2024-03-31",
            "operatingCashFlow": 500_000_000,
            "capitalExpenditure": -100_000_000,
            "freeCashFlow": 400_000_000,
            "cashAtEndOfPeriod": 282_000_000,
        }]
        result = _check_statement_completeness([], cash_flows, [])
        self.assertFalse(result["has_incomplete_statements"])
        self.assertEqual(result["incomplete_years"], [])

    def test_zero_filled_income_detected(self):
        """Revenue>0 but COGS=0, grossProfit=0 → warning."""
        income = [{
            "date": "2025-03-31",
            "revenue": 2_760_000_000,
            "costOfRevenue": 0,
            "grossProfit": 0,
            "operatingExpenses": 100_000_000,
            "netIncome": -1_100_000_000,
        }]
        result = _check_statement_completeness(income, [], [])
        self.assertTrue(result["has_incomplete_statements"])
        self.assertIn("2025", result["incomplete_years"])

    def test_balance_sheet_structural_invariant(self):
        """totalAssets>0 but totalLiabilitiesAndTotalEquity=0 → warning."""
        bs = [{
            "date": "2025-03-31",
            "totalAssets": 5_000_000_000,
            "totalLiabilitiesAndTotalEquity": 0,
        }]
        result = _check_statement_completeness([], [], bs)
        self.assertTrue(result["has_incomplete_statements"])
        self.assertIn("2025", result["incomplete_years"])

    def test_normal_balance_sheet_not_flagged(self):
        """Normal BS → no warning."""
        bs = [{
            "date": "2024-03-31",
            "totalAssets": 5_000_000_000,
            "totalLiabilitiesAndTotalEquity": 5_000_000_000,
        }]
        result = _check_statement_completeness([], [], bs)
        self.assertFalse(result["has_incomplete_statements"])

    def test_post_divestiture_sparse_bs_not_flagged(self):
        """Legitimate zero inventory/PP&E → no warning (totalAssets and liab+eq both present)."""
        bs = [{
            "date": "2024-03-31",
            "totalAssets": 2_000_000_000,
            "totalLiabilitiesAndTotalEquity": 2_000_000_000,
            "inventory": 0,
            "propertyPlantEquipmentNet": 0,
        }]
        result = _check_statement_completeness([], [], bs)
        self.assertFalse(result["has_incomplete_statements"])

    def test_zero_assets_not_flagged_when_inactive(self):
        """totalAssets=0 for a dissolved (not actively trading) company → no warning."""
        bs = [{"date": "2024-03-31", "totalAssets": 0, "totalLiabilitiesAndTotalEquity": 0}]
        result = _check_statement_completeness([], [], bs, is_actively_trading=False)
        self.assertFalse(result["has_incomplete_statements"])

    def test_zero_assets_flagged_when_active(self):
        """totalAssets=0 for an actively trading company → warning."""
        bs = [{"date": "2024-03-31", "totalAssets": 0, "totalLiabilitiesAndTotalEquity": 0}]
        result = _check_statement_completeness([], [], bs, is_actively_trading=True)
        self.assertTrue(result["has_incomplete_statements"])


class TestFcfHistoryExclusion(unittest.TestCase):
    """Tests for exclude_years in history builders."""

    def _make_income(self, year: str, revenue: float) -> dict:
        return {"date": f"{year}-03-31", "revenue": revenue}

    def _make_cashflow(self, year: str, fcf: float) -> dict:
        return {"date": f"{year}-03-31", "freeCashFlow": fcf}

    def test_incomplete_years_excluded_from_fcf_history(self):
        """Zero-filled year omitted from derived arrays."""
        income = [self._make_income("2025", 2.76e9), self._make_income("2024", 2.5e9)]
        cashflows = [
            self._make_cashflow("2025", 0),
            self._make_cashflow("2024", 300_000_000),
        ]
        history = _fcf_margin_history_pct(income, cashflows, exclude_years={"2025"})
        years = [h["date"][:4] for h in history]
        self.assertNotIn("2025", years)
        self.assertIn("2024", years)

    def test_latest_fcf_margin_uses_clean_history(self):
        """latest/trough computed from non-excluded data."""
        income = [
            self._make_income("2025", 2.76e9),
            self._make_income("2024", 2.5e9),
            self._make_income("2023", 2.3e9),
        ]
        cashflows = [
            self._make_cashflow("2025", 0),
            self._make_cashflow("2024", 300_000_000),
            self._make_cashflow("2023", 250_000_000),
        ]
        history = _fcf_margin_history_pct(income, cashflows, exclude_years={"2025"})
        self.assertEqual(len(history), 2)
        # Latest should be 2024's margin, not 2025's zero
        latest = history[0]["fcf_margin_pct"]
        self.assertGreater(latest, 0)

    def test_revenue_history_excludes_years(self):
        """Revenue history excludes specified years."""
        income = [
            self._make_income("2025", 2.76e9),
            self._make_income("2024", 2.5e9),
        ]
        history = _revenue_history_billions(income, exclude_years={"2025"})
        years = [h["date"][:4] for h in history]
        self.assertNotIn("2025", years)
        self.assertIn("2024", years)


if __name__ == "__main__":
    unittest.main()
