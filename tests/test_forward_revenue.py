"""Tests for forward_revenue_b in derived data and contradiction detection."""

import unittest


class TestForwardRevenueDerived(unittest.TestCase):
    """Verify forward_revenue_b is extracted from excluded incomplete years."""

    def _make_statements(self, fy2025_revenue=2_762_000_000):
        """Build income statements with an incomplete FY2025."""
        return [
            {"date": "2025-12-31", "revenue": fy2025_revenue,
             "costOfRevenue": 0, "grossProfit": 0,
             "operatingIncome": 5_000_000, "interestExpense": 100_000_000,
             "ebitda": 100_000_000, "netIncome": -1_100_000_000,
             "netIncomeFromContinuingOperations": -102_000_000,
             "weightedAverageShsOut": 77_000_000,
             "weightedAverageShsOutDil": 77_000_000,
             "operatingExpenses": 0},
            {"date": "2024-12-31", "revenue": 10_700_000_000,
             "costOfRevenue": 8_400_000_000, "grossProfit": 2_300_000_000,
             "operatingIncome": 250_000_000, "interestExpense": 140_000_000,
             "ebitda": 500_000_000, "netIncome": -360_000_000,
             "netIncomeFromContinuingOperations": -360_000_000,
             "weightedAverageShsOut": 77_000_000,
             "weightedAverageShsOutDil": 77_000_000,
             "operatingExpenses": 2_400_000_000},
        ]

    def test_forward_revenue_set_from_excluded_year(self):
        """forward_revenue_b populated from most recent incomplete year with revenue."""
        from edenfintech_scanner_bootstrap.fmp import (
            _check_statement_completeness,
            _revenue_history_billions,
            _extract_forward_revenue_b,
        )
        income = self._make_statements()
        cash_flows = [
            {"date": "2025-12-31", "operatingCashFlow": 0, "capitalExpenditure": 0,
             "freeCashFlow": 0, "cashAtEndOfPeriod": 280_000_000},
            {"date": "2024-12-31", "operatingCashFlow": 160_000_000,
             "capitalExpenditure": -210_000_000, "freeCashFlow": -66_000_000,
             "cashAtEndOfPeriod": 49_000_000},
        ]
        balance_sheets = [
            {"date": "2025-12-31", "totalAssets": 2_400_000_000,
             "totalLiabilitiesAndTotalEquity": 0},
            {"date": "2024-12-31", "totalAssets": 4_600_000_000,
             "totalLiabilitiesAndTotalEquity": 4_600_000_000},
        ]
        dq = _check_statement_completeness(income, cash_flows, balance_sheets)
        exclude_years = set(dq["incomplete_years"])
        forward = _extract_forward_revenue_b(income, exclude_years)
        self.assertAlmostEqual(forward, 2.762, places=3)

    def test_forward_revenue_none_when_no_excluded_years(self):
        """forward_revenue_b is None when no years are excluded."""
        from edenfintech_scanner_bootstrap.fmp import _extract_forward_revenue_b
        income = self._make_statements()
        forward = _extract_forward_revenue_b(income, set())
        self.assertIsNone(forward)

    def test_forward_revenue_none_when_excluded_year_has_zero_revenue(self):
        """forward_revenue_b is None when excluded year has zero revenue."""
        from edenfintech_scanner_bootstrap.fmp import _extract_forward_revenue_b
        income = self._make_statements(fy2025_revenue=0)
        forward = _extract_forward_revenue_b(income, {"2025"})
        self.assertIsNone(forward)


class TestContradictionForwardRevenue(unittest.TestCase):
    """Verify detect_contradictions uses forward_revenue_b when available."""

    def _make_overlay(self, revenue_b=2.79):
        return {
            "analysis_inputs": {
                "base_case_assumptions": {
                    "revenue_b": revenue_b,
                    "fcf_margin_pct": 3.0,
                    "shares_m": 77.288,
                },
            },
        }

    def _make_raw(self, latest_revenue_b=10.7, forward_revenue_b=None):
        derived = {
            "latest_revenue_b": latest_revenue_b,
            "trough_revenue_b": 9.78,
            "latest_fcf_margin_pct": -0.62,
            "shares_m_latest": 77.288,
        }
        if forward_revenue_b is not None:
            derived["forward_revenue_b"] = forward_revenue_b
        return {"fmp_context": {"derived": derived}}

    def test_no_contradiction_when_forward_revenue_matches(self):
        """Analyst's $2.79B matches forward_revenue_b — no revenue contradiction."""
        from edenfintech_scanner_bootstrap.validator import detect_contradictions
        overlay = self._make_overlay(revenue_b=2.79)
        raw = self._make_raw(latest_revenue_b=10.7, forward_revenue_b=2.762)
        contras = detect_contradictions(overlay, raw)
        revenue_contras = [c for c in contras if c["field"] == "revenue_b"]
        self.assertEqual(len(revenue_contras), 0)

    def test_contradiction_without_forward_revenue(self):
        """Without forward_revenue_b, $2.79B vs $10.7B triggers HIGH contradiction."""
        from edenfintech_scanner_bootstrap.validator import detect_contradictions
        overlay = self._make_overlay(revenue_b=2.79)
        raw = self._make_raw(latest_revenue_b=10.7, forward_revenue_b=None)
        contras = detect_contradictions(overlay, raw)
        revenue_contras = [c for c in contras if c["field"] == "revenue_b"]
        self.assertEqual(len(revenue_contras), 1)
        self.assertEqual(revenue_contras[0]["severity"], "HIGH")

    def test_contradiction_when_forward_revenue_also_mismatched(self):
        """Even with forward_revenue_b, a big gap still triggers contradiction."""
        from edenfintech_scanner_bootstrap.validator import detect_contradictions
        overlay = self._make_overlay(revenue_b=5.0)
        raw = self._make_raw(latest_revenue_b=10.7, forward_revenue_b=2.762)
        contras = detect_contradictions(overlay, raw)
        revenue_contras = [c for c in contras if c["field"] == "revenue_b"]
        self.assertEqual(len(revenue_contras), 1)


if __name__ == "__main__":
    unittest.main()
