from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edenfintech_scanner_bootstrap.config import load_config
from edenfintech_scanner_bootstrap.importers import build_scan_input, build_scan_input_file
from edenfintech_scanner_bootstrap.pipeline import run_scan


FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "raw"


class ConfigTest(unittest.TestCase):
    def test_load_config_reads_dotenv_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text(
                "FMP_API_KEY=fmp-test\n"
                "GEMINI_API_KEY=gemini-test\n"
                "OPENAI_API_KEY=openai-test\n"
                "CODEX_JUDGE_MODEL=gpt-5-codex\n"
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(dotenv_path)

        self.assertEqual(config.fmp_api_key, "fmp-test")
        self.assertEqual(config.gemini_api_key, "gemini-test")
        self.assertEqual(config.openai_api_key, "openai-test")
        self.assertEqual(config.codex_judge_model, "gpt-5-codex")


class ImporterE2ETest(unittest.TestCase):
    def test_raw_bundle_imports_and_runs_scan(self) -> None:
        raw_input_path = FIXTURES_ROOT / "ranked_candidate_bundle.json"
        scan_input = build_scan_input_file(raw_input_path)

        self.assertEqual(scan_input["candidates"][0]["ticker"], "RAW1")
        self.assertEqual(scan_input["candidates"][0]["analysis"]["base_case"]["multiple"], 20.0)

        artifacts = run_scan(scan_input)

        self.assertEqual(len(artifacts.report_json["ranked_candidates"]), 1)
        ranked = artifacts.report_json["ranked_candidates"][0]
        self.assertEqual(ranked["ticker"], "RAW1")
        self.assertEqual(artifacts.judge["verdict"], "APPROVE")

    def test_build_scan_input_validates_imported_payload(self) -> None:
        raw_payload = {
            "scan_parameters": {
                "scan_mode": "specific_tickers",
                "focus": "BROKEN",
            },
            "raw_candidates": [
                {
                    "ticker": "BROKEN",
                    "cluster_name": "broken-cluster",
                    "industry": "Industrial Components",
                    "current_price": 20.0,
                    "market_snapshot": {"pct_off_ath": 75.0},
                    "screening_inputs": {
                        "industry_understandable": True,
                        "industry_in_secular_decline": False,
                        "double_plus_potential": True,
                        "solvency": {"verdict": "PASS", "evidence": "ok"},
                        "dilution": {"verdict": "PASS", "evidence": "ok"},
                        "revenue_growth": {"verdict": "PASS", "evidence": "ok"},
                        "roic": {"verdict": "PASS", "evidence": "ok"},
                        "valuation": {"verdict": "PASS", "evidence": "ok"}
                    }
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "analysis"):
            build_scan_input(raw_payload)


if __name__ == "__main__":
    unittest.main()
