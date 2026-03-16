"""Tests for persisting hardening result to raw/ directory."""

import json
import tempfile
import unittest
from pathlib import Path


class TestHardeningResultPersisted(unittest.TestCase):
    """Verify hardening-result.json is written to raw/ directory."""

    def test_hardening_result_written(self):
        """_process_single_ticker writes hardening-result.json in raw/."""
        from unittest.mock import MagicMock, patch
        from edenfintech_scanner_bootstrap.scanner import _process_single_ticker
        from edenfintech_scanner_bootstrap.automation import AutoAnalyzeResult

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            raw_dir = out_dir / "TEST" / "raw"
            raw_dir.mkdir(parents=True)

            auto_result = AutoAnalyzeResult(
                ticker="TEST",
                finalized_overlay={
                    "structured_candidates": [{
                        "screening_inputs": {"solvency": {"verdict": "PASS", "evidence": "ok"}},
                        "analysis_inputs": {
                            "base_case_assumptions": {"revenue_b": 1.0, "fcf_margin_pct": 5.0, "shares_m": 50.0},
                            "probability": {"base_probability_pct": 60.0},
                            "dominant_risk_type": "Operational/Financial",
                        },
                    }],
                },
                validator_verdict={"verdict": "APPROVE"},
                epistemic_result={},
                retries_used=0,
                raw_bundle={
                    "raw_candidates": [{
                        "ticker": "TEST",
                        "data_quality": {"has_incomplete_statements": False},
                        "fmp_context": {"derived": {"latest_revenue_b": 1.0}},
                    }],
                },
            )

            config = MagicMock()
            config.llm_provider = "openai"

            with patch("edenfintech_scanner_bootstrap.scanner.run_scan") as mock_scan:
                mock_scan.return_value = MagicMock(
                    report_json={"ranked_candidates": [], "executive_summary": []},
                    report_markdown="# Report",
                )
                _process_single_ticker(
                    "TEST", auto_result,
                    config=config,
                    out_dir=out_dir,
                )

            hardening_path = raw_dir / "hardening-result.json"
            self.assertTrue(hardening_path.exists(), "hardening-result.json not written")
            data = json.loads(hardening_path.read_text())
            self.assertIn("evidence_quality", data)
            self.assertIn("thesis_break", data)
            self.assertIn("data_quality", data)


if __name__ == "__main__":
    unittest.main()
