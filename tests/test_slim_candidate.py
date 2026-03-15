"""Tests for _build_slim_candidate context deduplication."""

import unittest


class TestBuildSlimCandidate(unittest.TestCase):
    """Verify _build_slim_candidate strips bulky financial arrays."""

    def _make_raw_candidate(self) -> dict:
        """Build a minimal raw_candidate with realistic fmp_context structure."""
        return {
            "ticker": "TEST",
            "industry": "Testing",
            "current_price": 10.0,
            "trailing_ratios": {"interest_coverage": 2.5},
            "market_snapshot": {"current_price": 10.0, "all_time_high": 50.0},
            "gemini_context": {
                "research_notes": [{"claim": "Test claim", "source_title": "Test"}],
            },
            "data_quality": {"has_incomplete_statements": False},
            "fmp_context": {
                "profile": {"symbol": "TEST", "companyName": "Test Corp"},
                "quote": {"price": 10.0, "volume": 100000},
                "derived": {
                    "revenue_history_b": [{"date": "2025-12-31", "revenue_b": 1.0}],
                    "shares_m_latest": 50.0,
                },
                "annual_income_statements": [
                    {"date": "2025-12-31", "revenue": 1000000000, "ebit": 50000000},
                    {"date": "2024-12-31", "revenue": 900000000, "ebit": 45000000},
                    {"date": "2023-12-31", "revenue": 800000000, "ebit": 40000000},
                ],
                "annual_cash_flows": [
                    {"date": "2025-12-31", "freeCashFlow": 30000000},
                    {"date": "2024-12-31", "freeCashFlow": 25000000},
                ],
                "annual_balance_sheets": [
                    {"date": "2025-12-31", "totalAssets": 500000000},
                    {"date": "2024-12-31", "totalAssets": 480000000},
                    {"date": "2023-12-31", "totalAssets": 460000000},
                    {"date": "2022-12-31", "totalAssets": 440000000},
                    {"date": "2021-12-31", "totalAssets": 420000000},
                ],
            },
        }

    def test_slim_strips_statements(self):
        """Bulky financial arrays replaced with placeholder strings."""
        from edenfintech_scanner_bootstrap.analyst import _build_slim_candidate

        raw = self._make_raw_candidate()
        slim = _build_slim_candidate(raw)

        # Each array replaced with a string containing the period count
        self.assertIsInstance(slim["fmp_context"]["annual_income_statements"], str)
        self.assertIn("3 periods", slim["fmp_context"]["annual_income_statements"])

        self.assertIsInstance(slim["fmp_context"]["annual_cash_flows"], str)
        self.assertIn("2 periods", slim["fmp_context"]["annual_cash_flows"])

        self.assertIsInstance(slim["fmp_context"]["annual_balance_sheets"], str)
        self.assertIn("5 periods", slim["fmp_context"]["annual_balance_sheets"])

    def test_slim_preserves_other_keys(self):
        """Non-financial keys remain intact."""
        from edenfintech_scanner_bootstrap.analyst import _build_slim_candidate

        raw = self._make_raw_candidate()
        slim = _build_slim_candidate(raw)

        # Top-level keys preserved
        self.assertEqual(slim["ticker"], "TEST")
        self.assertEqual(slim["trailing_ratios"], {"interest_coverage": 2.5})
        self.assertEqual(slim["market_snapshot"]["current_price"], 10.0)
        self.assertEqual(slim["gemini_context"]["research_notes"][0]["claim"], "Test claim")
        self.assertFalse(slim["data_quality"]["has_incomplete_statements"])

        # fmp_context sub-keys preserved
        self.assertEqual(slim["fmp_context"]["profile"]["symbol"], "TEST")
        self.assertEqual(slim["fmp_context"]["quote"]["price"], 10.0)
        self.assertEqual(slim["fmp_context"]["derived"]["shares_m_latest"], 50.0)

    def test_slim_does_not_mutate_original(self):
        """Original raw_candidate's fmp_context arrays unchanged after call."""
        from edenfintech_scanner_bootstrap.analyst import _build_slim_candidate

        raw = self._make_raw_candidate()
        original_income_count = len(raw["fmp_context"]["annual_income_statements"])
        original_cf_count = len(raw["fmp_context"]["annual_cash_flows"])
        original_bs_count = len(raw["fmp_context"]["annual_balance_sheets"])

        _build_slim_candidate(raw)

        # Original arrays still intact
        self.assertIsInstance(raw["fmp_context"]["annual_income_statements"], list)
        self.assertEqual(len(raw["fmp_context"]["annual_income_statements"]), original_income_count)
        self.assertIsInstance(raw["fmp_context"]["annual_cash_flows"], list)
        self.assertEqual(len(raw["fmp_context"]["annual_cash_flows"]), original_cf_count)
        self.assertIsInstance(raw["fmp_context"]["annual_balance_sheets"], list)
        self.assertEqual(len(raw["fmp_context"]["annual_balance_sheets"]), original_bs_count)

    def test_slim_handles_missing_fmp_context(self):
        """No fmp_context key does not crash."""
        from edenfintech_scanner_bootstrap.analyst import _build_slim_candidate

        raw = {"ticker": "NOFMP", "industry": "Testing"}
        slim = _build_slim_candidate(raw)
        self.assertEqual(slim["ticker"], "NOFMP")
        self.assertNotIn("fmp_context", slim)


if __name__ == "__main__":
    unittest.main()
