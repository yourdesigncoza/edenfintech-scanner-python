from __future__ import annotations

import json
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.config import AppConfig
from edenfintech_scanner_bootstrap.fmp import FmpClient, build_fmp_bundle_with_config, build_raw_candidate_from_fmp


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "fmp"


def _load_fixture(name: str):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _fixture_transport(mapping: dict[str, str]):
    def transport(endpoint: str, params: dict[str, str]):
        if endpoint not in mapping:
            raise AssertionError(f"unexpected endpoint: {endpoint}")
        return _load_fixture(mapping[endpoint])

    return transport


class FmpTest(unittest.TestCase):
    def test_client_parses_official_shape_fmp_payloads(self) -> None:
        client = FmpClient(
            "fmp-test-key",
            transport=_fixture_transport(
                {
                    "profile/RAW1": "official_profile_raw1.json",
                    "quote/RAW1": "official_quote_raw1.json",
                    "historical-price-full/RAW1": "official_historical_price_full_raw1.json",
                    "income-statement/RAW1": "official_income_statement_raw1.json",
                    "cash-flow-statement/RAW1": "official_cash_flow_statement_raw1.json",
                }
            ),
        )

        candidate = build_raw_candidate_from_fmp("RAW1", client)

        self.assertEqual(candidate["industry"], "Industrial Components")
        self.assertEqual(candidate["market_snapshot"]["all_time_high"], 92.31)
        self.assertEqual(candidate["market_snapshot"]["pct_off_ath"], 74.0)
        self.assertEqual(candidate["fmp_context"]["derived"]["latest_revenue_b"], 3.4)
        self.assertEqual(candidate["fmp_context"]["derived"]["shares_m_latest"], 110.0)
        self.assertEqual(candidate["fmp_context"]["derived"]["latest_fcf_margin_pct"], 10.0)

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
            transport=_fixture_transport(
                {
                    "profile/RAW1": "profile_raw1.json",
                    "quote/RAW1": "quote_raw1.json",
                    "historical-price-full/RAW1": "historical_price_full_raw1.json",
                    "income-statement/RAW1": "income_statement_raw1.json",
                    "cash-flow-statement/RAW1": "cash_flow_statement_raw1.json",
                }
            ),
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
                transport=_fixture_transport(
                    {
                        "profile/RAW1": "profile_raw1.json",
                        "quote/RAW1": "quote_raw1.json",
                        "historical-price-full/RAW1": "historical_price_full_raw1.json",
                        "income-statement/RAW1": "income_statement_raw1.json",
                        "cash-flow-statement/RAW1": "cash_flow_statement_raw1.json",
                    }
                ),
            )

    def test_raw_candidate_handles_unsorted_statements_and_year_mismatch(self) -> None:
        client = FmpClient(
            "fmp-test-key",
            transport=_fixture_transport(
                {
                    "profile/RAW1": "profile_raw1.json",
                    "quote/RAW1": "quote_raw1.json",
                    "historical-price-full/RAW1": "historical_price_full_raw1.json",
                    "income-statement/RAW1": "income_statement_raw1_unsorted.json",
                    "cash-flow-statement/RAW1": "cash_flow_statement_raw1_year_mismatch.json",
                }
            ),
        )
        candidate = build_raw_candidate_from_fmp("RAW1", client)

        self.assertEqual(candidate["fmp_context"]["derived"]["shares_m_latest"], 110.0)
        self.assertEqual(candidate["fmp_context"]["derived"]["latest_revenue_b"], 3.4)
        self.assertEqual(candidate["fmp_context"]["derived"]["latest_fcf_margin_pct"], 10.0)
        self.assertEqual(len(candidate["fmp_context"]["derived"]["fcf_margin_history_pct"]), 3)

    def test_raw_candidate_raises_controlled_error_for_missing_price_history(self) -> None:
        client = FmpClient(
            "fmp-test-key",
            transport=_fixture_transport(
                {
                    "profile/RAW1": "profile_raw1.json",
                    "quote/RAW1": "quote_raw1.json",
                    "historical-price-full/RAW1": "historical_price_full_raw1_empty.json",
                    "income-statement/RAW1": "income_statement_raw1.json",
                    "cash-flow-statement/RAW1": "cash_flow_statement_raw1.json",
                }
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "historical prices did not contain usable close data"):
            build_raw_candidate_from_fmp("RAW1", client)


if __name__ == "__main__":
    unittest.main()
