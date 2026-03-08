from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.config import AppConfig
from edenfintech_scanner_bootstrap.live_scan import run_live_scan
from edenfintech_scanner_bootstrap.review_package import build_review_package
from edenfintech_scanner_bootstrap.structured_analysis import finalize_structured_analysis_file


def _mock_fmp_transport(endpoint: str, params: dict[str, str]):
    responses = {
        "profile": [
            {
                "symbol": "RAW1",
                "companyName": "Raw One Holdings",
                "industry": "Industrial Components",
            }
        ],
        "quote": [
            {
                "symbol": "RAW1",
                "price": 24.0,
            }
        ],
        "historical-price-eod/full": [
            {"date": "2026-03-07", "close": 24.0},
            {"date": "2025-06-01", "close": 31.0},
            {"date": "2024-04-01", "close": 92.31},
        ],
        "income-statement": [
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
        "cash-flow-statement": [
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
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    for candidate in payload["structured_candidates"]:
        for provenance in candidate["field_provenance"]:
            provenance["review_note"] = (
                f"Reviewer checked {provenance['field_path']} against the fetched evidence bundle."
            )
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
    template_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    finalize_structured_analysis_file(
        template_path,
        reviewer="Test Reviewer",
        json_out=out_path,
        note="Reviewed against the fetched raw bundle.",
    )
    return out_path


class ReviewPackageTest(unittest.TestCase):
    def test_build_review_package_raw_bundle_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = build_review_package(
                ["RAW1"],
                out_dir=Path(tmpdir),
                config=_config(),
                fmp_transport=_mock_fmp_transport,
                gemini_transport=_mock_gemini_transport,
            )

            self.assertEqual(result.live_scan_result.stop_at, "raw-bundle")
            for key in [
                "fmp_raw",
                "gemini_raw",
                "merged_raw",
                "structured_analysis_template",
                "structured_analysis_draft",
                "review_checklist_json",
                "review_checklist_markdown",
                "review_note_suggestions_json",
                "review_note_suggestions_markdown",
                "review_package_manifest",
            ]:
                self.assertIn(key, result.written_paths)
                self.assertTrue(result.written_paths[key].exists())
            self.assertEqual(result.written_paths["fmp_raw"].parent.name, "raw")
            self.assertEqual(result.written_paths["structured_analysis_draft"].parent.name, "raw")
            self.assertEqual(result.written_paths["review_checklist_json"].parent.name, "review")
            self.assertEqual(result.written_paths["review_note_suggestions_json"].parent.name, "review")
            self.assertNotIn("scan_input", result.written_paths)
            manifest = json.loads(result.written_paths["review_package_manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["stop_at"], "raw-bundle")
            self.assertEqual(Path(manifest["directories"]["raw"]).name, "raw")
            self.assertEqual(Path(manifest["directories"]["review"]).name, "review")
            self.assertEqual(Path(manifest["directories"]["final"]).name, "final")

    def test_build_review_package_report_layout_with_finalized_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            raw_run = run_live_scan(
                ["RAW1"],
                out_dir=out_dir / "prep",
                stop_at="raw-bundle",
                config=_config(),
                fmp_transport=_mock_fmp_transport,
                gemini_transport=_mock_gemini_transport,
            )
            finalized_overlay = _finalized_overlay(
                raw_run.written_paths["structured_analysis_template"],
                out_dir / "structured-analysis-finalized.json",
            )

            result = build_review_package(
                ["RAW1"],
                out_dir=out_dir / "package",
                structured_analysis_path=finalized_overlay,
                config=_config(),
                fmp_transport=_mock_fmp_transport,
                gemini_transport=_mock_gemini_transport,
            )

            self.assertEqual(result.live_scan_result.stop_at, "report")
            for key in [
                "scan_input",
                "report_json",
                "report_markdown",
                "execution_log",
                "judge_json",
                "structured_analysis_finalized",
                "review_checklist_json",
                "review_note_suggestions_json",
            ]:
                self.assertIn(key, result.written_paths)
                self.assertTrue(result.written_paths[key].exists())
            self.assertEqual(result.written_paths["merged_raw"].parent.name, "raw")
            self.assertEqual(result.written_paths["review_checklist_json"].parent.name, "review")
            self.assertEqual(result.written_paths["structured_analysis_finalized"].parent.name, "final")
            self.assertEqual(result.written_paths["report_json"].parent.name, "final")
            packaged_overlay = json.loads(result.written_paths["structured_analysis_finalized"].read_text(encoding="utf-8"))
            original_overlay = json.loads(finalized_overlay.read_text(encoding="utf-8"))
            self.assertEqual(packaged_overlay, original_overlay)
            manifest = json.loads(result.written_paths["review_package_manifest"].read_text(encoding="utf-8"))
            self.assertIn("structured_analysis_finalized", manifest["artifacts"])
            self.assertEqual(Path(manifest["directories"]["final"]).name, "final")


if __name__ == "__main__":
    unittest.main()
