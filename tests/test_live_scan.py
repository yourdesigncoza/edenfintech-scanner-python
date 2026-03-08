from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.config import AppConfig
from edenfintech_scanner_bootstrap.live_scan import run_live_scan


def _mock_fmp_transport(endpoint: str, params: dict[str, str]):
    responses = {
        "profile/RAW1": [
            {
                "symbol": "RAW1",
                "companyName": "Raw One Holdings",
                "industry": "Industrial Components",
            }
        ],
        "quote/RAW1": [
            {
                "symbol": "RAW1",
                "price": 24.0,
            }
        ],
        "historical-price-full/RAW1": {
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
        ],
    }
    return responses[endpoint]


def _mock_gemini_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
    return {
        "text": (
            '{"research_notes":[{"claim":"Demand is improving.","source_title":"Investor deck","source_url":"https://example.com/deck"}],'
            '"catalyst_evidence":[{"claim":"Pricing reset underway.","source_title":"Call","source_url":"https://example.com/call"}],'
            '"risk_evidence":[{"claim":"Execution risk remains.","source_title":"10-K","source_url":"https://example.com/10k"}],'
            '"management_observations":[],'
            '"moat_observations":[{"claim":"Qualification cycles are sticky.","source_title":"Industry note","source_url":"https://example.com/note"}],'
            '"precedent_observations":[],'
            '"epistemic_anchors":[]}'
        )
    }


def _config() -> AppConfig:
    return AppConfig(
        fmp_api_key="fmp-test-key",
        gemini_api_key="gemini-test-key",
        openai_api_key=None,
        codex_judge_model="gpt-5-codex",
    )


class LiveScanTest(unittest.TestCase):
    def test_run_live_scan_stops_honestly_at_raw_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_live_scan(
                ["RAW1"],
                out_dir=Path(tmpdir),
                stop_at="raw-bundle",
                config=_config(),
                fmp_transport=_mock_fmp_transport,
                gemini_transport=_mock_gemini_transport,
            )

            self.assertEqual(result.stop_at, "raw-bundle")
            self.assertIn("merged_raw", result.written_paths)
            self.assertIn("structured_analysis_template", result.written_paths)
            self.assertNotIn("scan_input", result.written_paths)

    def test_run_live_scan_can_produce_report_with_structured_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            raw_result = run_live_scan(
                ["RAW1"],
                out_dir=out_dir,
                stop_at="raw-bundle",
                config=_config(),
                fmp_transport=_mock_fmp_transport,
                gemini_transport=_mock_gemini_transport,
            )

            report_result = run_live_scan(
                ["RAW1"],
                out_dir=out_dir / "report-run",
                stop_at="report",
                structured_analysis_path=raw_result.written_paths["structured_analysis_template"],
                config=_config(),
                fmp_transport=_mock_fmp_transport,
                gemini_transport=_mock_gemini_transport,
            )

            self.assertEqual(report_result.stop_at, "report")
            self.assertIn("report_json", report_result.written_paths)
            self.assertTrue(report_result.written_paths["report_json"].exists())
            self.assertTrue(report_result.written_paths["judge_json"].exists())

    def test_run_live_scan_requires_structured_overlay_for_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "structured_analysis_path is required"):
                run_live_scan(
                    ["RAW1"],
                    out_dir=Path(tmpdir),
                    stop_at="report",
                    config=_config(),
                    fmp_transport=_mock_fmp_transport,
                    gemini_transport=_mock_gemini_transport,
                )


if __name__ == "__main__":
    unittest.main()
