"""Tests for discontinued operations flag and isActivelyTrading."""
import unittest
from edenfintech_scanner_bootstrap.fmp import _compute_trailing_ratios


class TestDiscontinuedOpsFlag(unittest.TestCase):
    """Tests for discontinued_ops_flag in trailing ratios."""

    def _make_statements(self, net_income, continuing_ops=None):
        inc = [{
            "revenue": 2_760_000_000,
            "operatingIncome": 100_000_000,
            "interestExpense": 50_000_000,
            "ebitda": 200_000_000,
            "netIncome": net_income,
        }]
        if continuing_ops is not None:
            inc[0]["netIncomeFromContinuingOperations"] = continuing_ops
        cf = [{"operatingCashFlow": 300_000_000, "freeCashFlow": 200_000_000}]
        bs = [{
            "totalDebt": 1_000_000_000,
            "totalStockholdersEquity": 500_000_000,
            "totalCurrentAssets": 800_000_000,
            "totalCurrentLiabilities": 400_000_000,
        }]
        return inc, cf, bs

    def test_discontinued_ops_flag_large_gap(self):
        """-1.1B vs -102M → flag True."""
        inc, cf, bs = self._make_statements(-1_100_000_000, -102_700_000)
        result = _compute_trailing_ratios(inc, cf, bs)
        self.assertTrue(result["discontinued_ops_flag"])

    def test_discontinued_ops_flag_small_gap(self):
        """Similar values → flag False."""
        inc, cf, bs = self._make_statements(-100_000_000, -95_000_000)
        result = _compute_trailing_ratios(inc, cf, bs)
        self.assertFalse(result["discontinued_ops_flag"])

    def test_discontinued_ops_missing_field(self):
        """Field absent → flag None, no crash."""
        inc, cf, bs = self._make_statements(-100_000_000)
        result = _compute_trailing_ratios(inc, cf, bs)
        self.assertIsNone(result["discontinued_ops_flag"])

    def test_discontinued_ops_both_zero(self):
        """Both zero → flag stays None (no meaningful gap)."""
        inc, cf, bs = self._make_statements(0, 0)
        result = _compute_trailing_ratios(inc, cf, bs)
        # Both zero: continuing_ops != 0 is False, net_income != 0 is False
        # So the inner if doesn't fire, flag stays None
        self.assertIsNone(result["discontinued_ops_flag"])

    def test_discontinued_ops_exact_match(self):
        """Identical values → flag False."""
        inc, cf, bs = self._make_statements(500_000_000, 500_000_000)
        result = _compute_trailing_ratios(inc, cf, bs)
        self.assertFalse(result["discontinued_ops_flag"])


if __name__ == "__main__":
    unittest.main()
