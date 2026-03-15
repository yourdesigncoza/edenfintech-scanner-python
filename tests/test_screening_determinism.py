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


if __name__ == "__main__":
    unittest.main()
