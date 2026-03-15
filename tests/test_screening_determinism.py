"""Tests for deterministic screening enhancements."""
import unittest

from edenfintech_scanner_bootstrap.fmp import _compute_trailing_ratios


class TestTrailingRatiosNewFields(unittest.TestCase):
    """Verify roic_pct and sbc_pct_of_revenue in trailing ratios."""

    def _make_statements(
        self,
        *,
        revenue=1_000_000_000,
        operating_income=100_000_000,
        interest_expense=20_000_000,
        income_tax=25_000_000,
        income_before_tax=80_000_000,
        net_income=55_000_000,
        ebitda=150_000_000,
        ocf=120_000_000,
        fcf=80_000_000,
        sbc=30_000_000,
        total_debt=500_000_000,
        total_equity=300_000_000,
        cash=50_000_000,
        current_assets=200_000_000,
        current_liabilities=150_000_000,
    ):
        income = [{
            "revenue": revenue,
            "operatingIncome": operating_income,
            "interestExpense": interest_expense,
            "incomeTaxExpense": income_tax,
            "incomeBeforeTax": income_before_tax,
            "netIncome": net_income,
            "ebitda": ebitda,
        }]
        cashflows = [{
            "operatingCashFlow": ocf,
            "freeCashFlow": fcf,
            "stockBasedCompensation": sbc,
        }]
        balance = [{
            "totalDebt": total_debt,
            "totalStockholdersEquity": total_equity,
            "cashAndCashEquivalents": cash,
            "totalCurrentAssets": current_assets,
            "totalCurrentLiabilities": current_liabilities,
        }]
        return income, cashflows, balance

    def test_roic_pct_computed(self):
        """ROIC = NOPAT / invested_capital * 100."""
        inc, cf, bs = self._make_statements(
            operating_income=100_000_000,
            income_tax=25_000_000,
            income_before_tax=80_000_000,
            total_equity=300_000_000,
            total_debt=500_000_000,
            cash=50_000_000,
        )
        result = _compute_trailing_ratios(inc, cf, bs)
        self.assertIsNotNone(result["roic_pct"])
        # tax_rate = 25M / 80M = 0.3125
        # NOPAT = 100M * (1 - 0.3125) = 68.75M
        # invested_capital = 300M + 500M - 50M = 750M
        # ROIC = 68.75M / 750M * 100 = 9.17%
        self.assertAlmostEqual(result["roic_pct"], 9.17, places=1)

    def test_roic_pct_none_when_negative_equity(self):
        """ROIC returns None when invested capital <= 0."""
        inc, cf, bs = self._make_statements(
            total_equity=-500_000_000,
            total_debt=200_000_000,
            cash=50_000_000,
        )
        result = _compute_trailing_ratios(inc, cf, bs)
        self.assertIsNone(result["roic_pct"])

    def test_roic_pct_none_when_no_income_data(self):
        """ROIC returns None when income statements empty."""
        result = _compute_trailing_ratios([], [], [])
        self.assertIsNone(result["roic_pct"])

    def test_sbc_pct_of_revenue_computed(self):
        """SBC pct = stockBasedCompensation / revenue * 100."""
        inc, cf, bs = self._make_statements(
            revenue=1_000_000_000,
            sbc=60_000_000,
        )
        result = _compute_trailing_ratios(inc, cf, bs)
        self.assertAlmostEqual(result["sbc_pct_of_revenue"], 6.0, places=1)

    def test_sbc_pct_none_when_no_revenue(self):
        """SBC pct returns None when revenue is zero."""
        inc, cf, bs = self._make_statements(revenue=0, sbc=30_000_000)
        result = _compute_trailing_ratios(inc, cf, bs)
        self.assertIsNone(result["sbc_pct_of_revenue"])

    def test_sbc_pct_none_when_no_sbc_field(self):
        """SBC pct returns None when stockBasedCompensation not in cashflow."""
        inc, cf, bs = self._make_statements()
        del cf[0]["stockBasedCompensation"]
        result = _compute_trailing_ratios(inc, cf, bs)
        self.assertIsNone(result["sbc_pct_of_revenue"])


from edenfintech_scanner_bootstrap.field_generation import _screening_inputs


class TestDeterministicScreeningVerdicts(unittest.TestCase):
    """Verify strengthened screening verdicts use trailing_ratios."""

    def _make_raw_candidate(
        self,
        *,
        interest_coverage=3.0,
        debt_to_equity=0.5,
        current_ratio=1.5,
        fcf_margin_pct=5.0,
        roic_pct=12.0,
        sbc_pct_of_revenue=2.0,
        pct_off_ath=70.0,
        latest_fcf_margin_pct=5.0,
        latest_revenue_b=10.0,
        trough_revenue_b=8.0,
        share_history=None,
    ):
        """Build a minimal raw_candidate with trailing_ratios."""
        income_stmts = []
        if share_history:
            for i, s in enumerate(share_history):
                income_stmts.append({"calendarYear": str(2024 - i), "weightedAverageShsOutDil": s})
        return {
            "industry": "Healthcare",
            "market_snapshot": {"pct_off_ath": pct_off_ath},
            "trailing_ratios": {
                "interest_coverage": interest_coverage,
                "debt_to_equity": debt_to_equity,
                "current_ratio": current_ratio,
                "fcf_margin_pct": fcf_margin_pct,
                "roic_pct": roic_pct,
                "sbc_pct_of_revenue": sbc_pct_of_revenue,
            },
            "fmp_context": {
                "derived": {
                    "latest_fcf_margin_pct": latest_fcf_margin_pct,
                    "latest_revenue_b": latest_revenue_b,
                    "trough_revenue_b": trough_revenue_b,
                },
                "annual_income_statements": income_stmts,
            },
            "gemini_context": {},
        }

    # --- Solvency ---

    def test_solvency_fail_distressed(self):
        """FAIL when interest_coverage < 1.0 AND current_ratio < 1.0."""
        rc = self._make_raw_candidate(interest_coverage=0.5, current_ratio=0.8)
        result, _ = _screening_inputs(rc)
        self.assertEqual(result["solvency"]["verdict"], "FAIL")

    def test_solvency_fail_negative_equity(self):
        """FAIL when interest_coverage < 1.0 AND equity negative (debt_to_equity=None)."""
        rc = self._make_raw_candidate(interest_coverage=0.5, debt_to_equity=None)
        result, _ = _screening_inputs(rc)
        self.assertEqual(result["solvency"]["verdict"], "FAIL")

    def test_solvency_pass_healthy(self):
        """PASS when interest_coverage >= 2.0 AND current_ratio >= 1.0."""
        rc = self._make_raw_candidate(interest_coverage=3.0, current_ratio=1.5)
        result, _ = _screening_inputs(rc)
        self.assertEqual(result["solvency"]["verdict"], "PASS")

    def test_solvency_borderline_mixed(self):
        """BORDERLINE when interest_coverage >= 1.0 but < 2.0."""
        rc = self._make_raw_candidate(interest_coverage=1.5, current_ratio=1.2)
        result, _ = _screening_inputs(rc)
        self.assertEqual(result["solvency"]["verdict"], "BORDERLINE_PASS")

    # --- ROIC ---

    def test_roic_fail_below_threshold(self):
        """FAIL when roic_pct < 6.0."""
        rc = self._make_raw_candidate(roic_pct=4.0)
        result, _ = _screening_inputs(rc)
        self.assertEqual(result["roic"]["verdict"], "FAIL")

    def test_roic_borderline_mid_range(self):
        """BORDERLINE when 6.0 <= roic_pct < 10.0."""
        rc = self._make_raw_candidate(roic_pct=8.0)
        result, _ = _screening_inputs(rc)
        self.assertEqual(result["roic"]["verdict"], "BORDERLINE_PASS")

    def test_roic_pass_above_threshold(self):
        """PASS when roic_pct >= 10.0."""
        rc = self._make_raw_candidate(roic_pct=15.0)
        result, _ = _screening_inputs(rc)
        self.assertEqual(result["roic"]["verdict"], "PASS")

    def test_roic_borderline_when_none(self):
        """BORDERLINE when roic_pct is None (not computable)."""
        rc = self._make_raw_candidate(roic_pct=None)
        result, _ = _screening_inputs(rc)
        self.assertEqual(result["roic"]["verdict"], "BORDERLINE_PASS")

    # --- Dilution + SBC ---

    def test_dilution_fail_high_sbc(self):
        """FAIL when sbc_pct_of_revenue > 5.0 AND share growth > 0."""
        rc = self._make_raw_candidate(
            sbc_pct_of_revenue=7.0,
            share_history=[110_000_000, 100_000_000],
        )
        result, _ = _screening_inputs(rc)
        self.assertEqual(result["dilution"]["verdict"], "FAIL")

    def test_dilution_pass_low_sbc(self):
        """PASS when share growth <= 5% and SBC <= 5%."""
        rc = self._make_raw_candidate(
            sbc_pct_of_revenue=3.0,
            share_history=[102_000_000, 100_000_000],
        )
        result, _ = _screening_inputs(rc)
        self.assertEqual(result["dilution"]["verdict"], "PASS")

    def test_dilution_sbc_ignored_when_no_growth(self):
        """SBC > 5% does NOT fail if shares are flat/declining."""
        rc = self._make_raw_candidate(
            sbc_pct_of_revenue=8.0,
            share_history=[100_000_000, 100_000_000],
        )
        result, _ = _screening_inputs(rc)
        self.assertNotEqual(result["dilution"]["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
