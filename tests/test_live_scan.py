from __future__ import annotations

import json
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


def _finalized_overlay(template_path: Path, out_path: Path) -> Path:
    payload = json.loads(template_path.read_text())
    payload["completion_status"] = "FINALIZED"
    payload["completion_note"] = "Reviewed against the fetched raw bundle."
    for candidate in payload["structured_candidates"]:
        candidate["screening_inputs"]["industry_understandable"] = True
        candidate["screening_inputs"]["double_plus_potential"] = True
        for check_name in ["solvency", "dilution", "revenue_growth", "roic", "valuation"]:
            candidate["screening_inputs"][check_name]["verdict"] = "PASS"
            candidate["screening_inputs"][check_name]["evidence"] = f"{check_name} grounded in fetched evidence."
        analysis = candidate["analysis_inputs"]
        analysis["margin_trend_gate"] = "PASS"
        analysis["final_cluster_status"] = "CLEAR_WINNER"
        analysis["catalyst_classification"] = "VALID_CATALYST"
        analysis["dominant_risk_type"] = "Operational/Financial"
        analysis["issues_and_fixes"] = "Structured issues and fixes."
        analysis["moat_assessment"] = "Structured moat assessment."
        analysis["thesis_summary"] = "Structured thesis."
        analysis["catalysts"] = ["Structured catalyst"]
        analysis["key_risks"] = ["Structured risk"]
        analysis["base_case_assumptions"]["discount_path"] = "Structured discount path."
        analysis["probability_inputs"]["base_rate"] = "Structured base rate."
        analysis["probability_inputs"]["likert_adjustments"] = "Structured likert adjustments."
        analysis["exception_candidate"]["reason"] = "No exception required."
        for key in ["q1_operational", "q2_regulatory", "q3_precedent", "q4_nonbinary", "q5_macro"]:
            candidate["epistemic_inputs"][key]["answer"] = "Yes"
            candidate["epistemic_inputs"][key]["justification"] = f"{key} structured justification."
            candidate["epistemic_inputs"][key]["evidence"] = f"{key} structured evidence."
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path


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
            self.assertIn("structured_analysis_draft", result.written_paths)
            self.assertNotIn("scan_input", result.written_paths)

    def test_run_live_scan_can_produce_report_with_finalized_structured_overlay(self) -> None:
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
            finalized_overlay = _finalized_overlay(
                raw_result.written_paths["structured_analysis_template"],
                out_dir / "structured-analysis-finalized.json",
            )

            report_result = run_live_scan(
                ["RAW1"],
                out_dir=out_dir / "report-run",
                stop_at="report",
                structured_analysis_path=finalized_overlay,
                config=_config(),
                fmp_transport=_mock_fmp_transport,
                gemini_transport=_mock_gemini_transport,
            )

            self.assertEqual(report_result.stop_at, "report")
            self.assertIn("report_json", report_result.written_paths)
            self.assertTrue(report_result.written_paths["report_json"].exists())
            self.assertTrue(report_result.written_paths["judge_json"].exists())

    def test_run_live_scan_rejects_unedited_template_for_report(self) -> None:
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

            with self.assertRaisesRegex(ValueError, "structured analysis schema validation failed|must be FINALIZED|placeholder"):
                run_live_scan(
                    ["RAW1"],
                    out_dir=out_dir / "report-run",
                    stop_at="report",
                    structured_analysis_path=raw_result.written_paths["structured_analysis_template"],
                    config=_config(),
                    fmp_transport=_mock_fmp_transport,
                    gemini_transport=_mock_gemini_transport,
                )

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

    def test_run_live_scan_rejects_overlay_from_stale_raw_bundle(self) -> None:
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
            finalized_overlay = _finalized_overlay(
                raw_result.written_paths["structured_analysis_template"],
                out_dir / "structured-analysis-finalized.json",
            )

            def updated_fmp_transport(endpoint: str, params: dict[str, str]):
                response = _mock_fmp_transport(endpoint, params)
                if endpoint == "quote/RAW1":
                    return [{"symbol": "RAW1", "price": 19.0}]
                return response

            with self.assertRaisesRegex(ValueError, "source bundle fingerprint does not match"):
                run_live_scan(
                    ["RAW1"],
                    out_dir=out_dir / "stale-run",
                    stop_at="scan-input",
                    structured_analysis_path=finalized_overlay,
                    config=_config(),
                    fmp_transport=updated_fmp_transport,
                    gemini_transport=_mock_gemini_transport,
                )

    def test_run_live_scan_rejects_malformed_structured_overlay_early(self) -> None:
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
            malformed_overlay = json.loads(raw_result.written_paths["structured_analysis_template"].read_text())
            malformed_overlay["completion_status"] = "FINALIZED"
            candidate = malformed_overlay["structured_candidates"][0]
            for check_name in ["solvency", "dilution", "revenue_growth", "roic", "valuation"]:
                candidate["screening_inputs"][check_name]["verdict"] = "PASS"
                candidate["screening_inputs"][check_name]["evidence"] = "ok"
            candidate["analysis_inputs"]["margin_trend_gate"] = "PASS"
            candidate["analysis_inputs"]["final_cluster_status"] = "CLEAR_WINNER"
            candidate["analysis_inputs"]["catalyst_classification"] = "VALID_CATALYST"
            candidate["analysis_inputs"]["dominant_risk_type"] = "Operational/Financial"
            candidate["analysis_inputs"]["catalysts"] = ["Structured catalyst"]
            candidate["analysis_inputs"]["key_risks"] = ["Structured risk"]
            candidate["analysis_inputs"]["issues_and_fixes"] = "Structured issues"
            candidate["analysis_inputs"]["moat_assessment"] = "Structured moat"
            candidate["analysis_inputs"]["thesis_summary"] = "Structured thesis"
            candidate["analysis_inputs"]["base_case_assumptions"]["discount_path"] = "Structured path"
            candidate["analysis_inputs"]["probability_inputs"]["base_rate"] = "Structured rate"
            candidate["analysis_inputs"]["probability_inputs"]["likert_adjustments"] = "Structured likert"
            candidate["analysis_inputs"]["exception_candidate"]["reason"] = "Not needed"
            candidate["epistemic_inputs"].pop("q5_macro")
            malformed_path = out_dir / "structured-analysis-malformed.json"
            malformed_path.write_text(json.dumps(malformed_overlay, indent=2))

            with self.assertRaisesRegex(ValueError, "structured analysis schema validation failed"):
                run_live_scan(
                    ["RAW1"],
                    out_dir=out_dir / "malformed-run",
                    stop_at="scan-input",
                    structured_analysis_path=malformed_path,
                    config=_config(),
                    fmp_transport=_mock_fmp_transport,
                    gemini_transport=_mock_gemini_transport,
                )


if __name__ == "__main__":
    unittest.main()
