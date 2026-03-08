from __future__ import annotations

import unittest

from edenfintech_scanner_bootstrap.config import AppConfig
from edenfintech_scanner_bootstrap.fmp import FmpClient, build_fmp_bundle_with_config, build_raw_candidate_from_fmp


def _mock_fmp_transport(endpoint: str, params: dict[str, str]):
    responses = {
        "profile/RAW1": [
            {
                "symbol": "RAW1",
                "companyName": "Raw One Holdings",
                "industry": "Industrial Components",
                "sector": "Industrials",
            }
        ],
        "quote/RAW1": [
            {
                "symbol": "RAW1",
                "price": 24.0,
            }
        ],
        "historical-price-full/RAW1": {
            "symbol": "RAW1",
            "historical": [
                {"date": "2026-03-07", "close": 24.0},
                {"date": "2025-06-01", "close": 31.0},
                {"date": "2024-04-01", "close": 92.31},
            ],
        },
        "income-statement/RAW1": [
            {
                "date": "2025-12-31",
                "revenue": 3_400_000_000,
                "weightedAverageShsOutDil": 110_000_000,
            },
            {
                "date": "2024-12-31",
                "revenue": 3_100_000_000,
                "weightedAverageShsOutDil": 112_000_000,
            },
            {
                "date": "2023-12-31",
                "revenue": 2_900_000_000,
                "weightedAverageShsOutDil": 114_000_000,
            },
        ],
        "cash-flow-statement/RAW1": [
            {
                "date": "2025-12-31",
                "freeCashFlow": 340_000_000,
            },
            {
                "date": "2024-12-31",
                "freeCashFlow": 248_000_000,
            },
            {
                "date": "2023-12-31",
                "freeCashFlow": 203_000_000,
            },
        ],
    }
    if endpoint not in responses:
        raise AssertionError(f"unexpected endpoint: {endpoint}")
    return responses[endpoint]


class FmpTest(unittest.TestCase):
    def test_client_builds_raw_bundle_with_derived_fields(self) -> None:
        config = AppConfig(
            fmp_api_key="fmp-test-key",
            gemini_api_key=None,
            openai_api_key=None,
            codex_judge_model="gpt-5-codex",
        )

        bundle = build_fmp_bundle_with_config(
            ["RAW1"],
            config=config,
            transport=_mock_fmp_transport,
        )

        self.assertEqual(bundle["scan_parameters"]["api"], "Financial Modeling Prep")
        candidate = bundle["raw_candidates"][0]
        self.assertEqual(candidate["ticker"], "RAW1")
        self.assertEqual(candidate["industry"], "Industrial Components")
        self.assertEqual(candidate["current_price"], 24.0)
        self.assertEqual(candidate["market_snapshot"]["all_time_high"], 92.31)
        self.assertEqual(candidate["market_snapshot"]["pct_off_ath"], 74.0)
        self.assertEqual(candidate["fmp_context"]["derived"]["shares_m_latest"], 110.0)
        self.assertEqual(candidate["fmp_context"]["derived"]["latest_revenue_b"], 3.4)
        self.assertEqual(candidate["fmp_context"]["derived"]["trough_revenue_b"], 2.9)
        self.assertEqual(candidate["fmp_context"]["derived"]["latest_fcf_margin_pct"], 10.0)
        self.assertEqual(candidate["fmp_context"]["derived"]["trough_fcf_margin_pct"], 7.0)

    def test_client_requires_fmp_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required configuration: fmp_api_key"):
            build_fmp_bundle_with_config(
                ["RAW1"],
                config=AppConfig(
                    fmp_api_key=None,
                    gemini_api_key=None,
                    openai_api_key=None,
                    codex_judge_model="gpt-5-codex",
                ),
                transport=_mock_fmp_transport,
            )

    def test_raw_candidate_handles_unsorted_statements_and_year_mismatch(self) -> None:
        def transport(endpoint: str, params: dict[str, str]):
            responses = {
                "profile/RAW1": [{"industry": "Industrial Components"}],
                "quote/RAW1": [{"price": 24.0}],
                "historical-price-full/RAW1": {
                    "historical": [
                        {"date": "2024-04-01", "close": 92.31},
                        {"date": "2026-03-07", "close": 24.0},
                    ]
                },
                "income-statement/RAW1": [
                    {"date": "2023-12-31", "revenue": 2_900_000_000, "weightedAverageShsOutDil": 114_000_000},
                    {"date": "2025-12-31", "revenue": 3_400_000_000, "weightedAverageShsOutDil": 110_000_000},
                    {"date": "2024-12-31", "revenue": 3_100_000_000, "weightedAverageShsOutDil": 112_000_000},
                ],
                "cash-flow-statement/RAW1": [
                    {"date": "2023-09-30", "freeCashFlow": 203_000_000},
                    {"date": "2025-09-30", "freeCashFlow": 340_000_000},
                    {"date": "2024-09-30", "freeCashFlow": 248_000_000},
                ],
            }
            return responses[endpoint]

        client = FmpClient("fmp-test-key", transport=transport)
        candidate = build_raw_candidate_from_fmp("RAW1", client)

        self.assertEqual(candidate["fmp_context"]["derived"]["shares_m_latest"], 110.0)
        self.assertEqual(candidate["fmp_context"]["derived"]["latest_revenue_b"], 3.4)
        self.assertEqual(candidate["fmp_context"]["derived"]["latest_fcf_margin_pct"], 10.0)
        self.assertEqual(len(candidate["fmp_context"]["derived"]["fcf_margin_history_pct"]), 3)

    def test_raw_candidate_raises_controlled_error_for_missing_price_history(self) -> None:
        def transport(endpoint: str, params: dict[str, str]):
            responses = {
                "profile/RAW1": [{"industry": "Industrial Components"}],
                "quote/RAW1": [{"price": 24.0}],
                "historical-price-full/RAW1": {"historical": []},
                "income-statement/RAW1": [
                    {"date": "2025-12-31", "revenue": 3_400_000_000, "weightedAverageShsOutDil": 110_000_000}
                ],
                "cash-flow-statement/RAW1": [
                    {"date": "2025-12-31", "freeCashFlow": 340_000_000}
                ],
            }
            return responses[endpoint]

        client = FmpClient("fmp-test-key", transport=transport)
        with self.assertRaisesRegex(RuntimeError, "historical prices did not contain usable close data"):
            build_raw_candidate_from_fmp("RAW1", client)


if __name__ == "__main__":
    unittest.main()
