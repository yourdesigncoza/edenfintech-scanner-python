"""Tests for the auto_analyze orchestrator.

Covers the full automated analysis flow:
  - Happy path: analyst APPROVE on first try, epistemic review, finalize with LLM_CONFIRMED
  - Retry path: validator REJECT triggers retry with objections, second APPROVE
  - Max retries exceeded: epistemic review still runs, overlay still finalized
  - Missing sector knowledge: warns but completes
  - Finalized overlay has completion_status=FINALIZED and LLM_CONFIRMED provenance
  - Epistemic PCS answers replace analyst's epistemic_inputs
  - AutoAnalyzeResult contains retries_used count
"""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

from edenfintech_scanner_bootstrap.automation import AutoAnalyzeResult, auto_analyze
from edenfintech_scanner_bootstrap.config import AppConfig
from edenfintech_scanner_bootstrap.structured_analysis import FINAL_PROVENANCE_STATUSES

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
LLM_RESPONSE_FIXTURE = FIXTURE_DIR / "analyst" / "llm-response-fixture.json"
RAW_BUNDLE_FIXTURE = FIXTURE_DIR / "raw" / "merged_candidate_bundle.json"


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text())


def _make_config() -> AppConfig:
    return AppConfig(
        fmp_api_key="test",
        gemini_api_key="test",
        openai_api_key=None,
        codex_judge_model="gpt-5-codex",
        anthropic_api_key="test-key",
        analyst_model="claude-sonnet-4-5-20250514",
    )


def _mock_analyst_transport(request_payload: dict) -> dict:
    """Returns the LLM response fixture as the analyst output."""
    raw_text = LLM_RESPONSE_FIXTURE.read_text()
    return {"text": raw_text, "stop_reason": "end_turn"}


def _mock_validator_transport_approve(request_payload: dict) -> dict:
    """Returns an APPROVE verdict."""
    return {
        "text": json.dumps({
            "verdict": "APPROVE",
            "questions": [
                {
                    "question_id": "bull_falsifiability",
                    "challenge": "Test challenge",
                    "evidence": "Test evidence",
                    "severity": "LOW",
                }
            ],
            "objections": [],
        }),
        "stop_reason": "end_turn",
    }


def _mock_validator_transport_reject(request_payload: dict) -> dict:
    """Returns a REJECT verdict with objections."""
    return {
        "text": json.dumps({
            "verdict": "REJECT",
            "questions": [
                {
                    "question_id": "bull_falsifiability",
                    "challenge": "Unsubstantiated claims",
                    "evidence": "No concrete evidence",
                    "severity": "HIGH",
                }
            ],
            "objections": [
                "Revenue assumptions lack supporting evidence",
                "FCF margin target appears overly optimistic",
            ],
        }),
        "stop_reason": "end_turn",
    }


def _mock_epistemic_transport(request_payload: dict) -> dict:
    """Returns 5 PCS answers."""
    pcs_answers = {
        "q1_operational": {
            "answer": "Yes",
            "justification": "Operational risk is manageable",
            "evidence": "Management has clear levers",
            "evidence_source": "10-K FY2024",
        },
        "q2_regulatory": {
            "answer": "Yes",
            "justification": "Regulatory risk is bounded",
            "evidence": "No material regulatory exposure",
            "evidence_source": "10-K FY2024",
        },
        "q3_precedent": {
            "answer": "Yes",
            "justification": "Historical precedents exist",
            "evidence": "Similar turnarounds in sector",
            "evidence_source": "Annual report 2023",
        },
        "q4_nonbinary": {
            "answer": "No",
            "justification": "Outcome is somewhat binary",
            "evidence": "Limited partial recovery paths",
            "evidence_source": "Earnings call Q3 2025",
        },
        "q5_macro": {
            "answer": "Yes",
            "justification": "Macro is secondary",
            "evidence": "Company-specific factors dominate",
            "evidence_source": "Investor presentation 2025",
        },
    }
    return {"text": json.dumps(pcs_answers), "stop_reason": "end_turn"}


def _mock_live_scan_result(tickers, *, out_dir, stop_at="raw-bundle", config=None, **kwargs):
    """Mock run_live_scan that writes the merged bundle fixture to out_dir."""
    from edenfintech_scanner_bootstrap.live_scan import LiveScanResult

    merged_bundle = _load_fixture(RAW_BUNDLE_FIXTURE)
    merged_path = out_dir / "merged-raw.json"
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    merged_path.write_text(json.dumps(merged_bundle, indent=2))

    return LiveScanResult(
        stop_at=stop_at,
        out_dir=out_dir,
        written_paths={"merged_raw": merged_path},
    )


class TestAutoAnalyze(unittest.TestCase):
    """Tests for auto_analyze orchestrator."""

    def setUp(self):
        self.config = _make_config()
        self.tmp_dir = tempfile.mkdtemp()
        self.out_dir = Path(self.tmp_dir)

    @patch("edenfintech_scanner_bootstrap.automation.run_live_scan", side_effect=_mock_live_scan_result)
    def test_happy_path_approve_first_try(self, mock_live_scan):
        """Full flow: analyst APPROVE on first try, epistemic review, finalize with LLM_CONFIRMED."""
        from edenfintech_scanner_bootstrap.analyst import ClaudeAnalystClient
        from edenfintech_scanner_bootstrap.validator import RedTeamValidatorClient
        from edenfintech_scanner_bootstrap.epistemic_reviewer import EpistemicReviewerClient

        result = auto_analyze(
            "RAW1",
            config=self.config,
            out_dir=self.out_dir,
            analyst_client=ClaudeAnalystClient(None, transport=_mock_analyst_transport),
            validator_client=RedTeamValidatorClient("test", transport=_mock_validator_transport_approve),
            epistemic_client=EpistemicReviewerClient("test", transport=_mock_epistemic_transport),
        )

        self.assertIsInstance(result, AutoAnalyzeResult)
        self.assertEqual(result.ticker, "RAW1")
        self.assertEqual(result.retries_used, 0)
        self.assertEqual(result.validator_verdict["verdict"], "APPROVE")
        self.assertEqual(result.finalized_overlay["completion_status"], "FINALIZED")

    @patch("edenfintech_scanner_bootstrap.automation.run_live_scan", side_effect=_mock_live_scan_result)
    def test_reject_then_approve_retry(self, mock_live_scan):
        """Validator REJECT triggers retry with objections, second attempt APPROVE."""
        from edenfintech_scanner_bootstrap.analyst import ClaudeAnalystClient
        from edenfintech_scanner_bootstrap.validator import RedTeamValidatorClient
        from edenfintech_scanner_bootstrap.epistemic_reviewer import EpistemicReviewerClient

        call_count = {"n": 0}

        def validator_transport(request_payload):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _mock_validator_transport_reject(request_payload)
            return _mock_validator_transport_approve(request_payload)

        result = auto_analyze(
            "RAW1",
            config=self.config,
            out_dir=self.out_dir,
            analyst_client=ClaudeAnalystClient(None, transport=_mock_analyst_transport),
            validator_client=RedTeamValidatorClient("test", transport=validator_transport),
            epistemic_client=EpistemicReviewerClient("test", transport=_mock_epistemic_transport),
        )

        self.assertEqual(result.retries_used, 1)
        self.assertEqual(result.validator_verdict["verdict"], "APPROVE")
        self.assertEqual(result.finalized_overlay["completion_status"], "FINALIZED")

    @patch("edenfintech_scanner_bootstrap.automation.run_live_scan", side_effect=_mock_live_scan_result)
    def test_max_retries_exceeded_still_finalizes(self, mock_live_scan):
        """After max retries with all REJECT, epistemic review still runs and overlay is finalized."""
        from edenfintech_scanner_bootstrap.analyst import ClaudeAnalystClient
        from edenfintech_scanner_bootstrap.validator import RedTeamValidatorClient
        from edenfintech_scanner_bootstrap.epistemic_reviewer import EpistemicReviewerClient

        result = auto_analyze(
            "RAW1",
            config=self.config,
            out_dir=self.out_dir,
            analyst_client=ClaudeAnalystClient(None, transport=_mock_analyst_transport),
            validator_client=RedTeamValidatorClient("test", transport=_mock_validator_transport_reject),
            epistemic_client=EpistemicReviewerClient("test", transport=_mock_epistemic_transport),
            max_retries=2,
        )

        self.assertEqual(result.retries_used, 2)
        self.assertEqual(result.validator_verdict["verdict"], "REJECT")
        # Epistemic review still runs and overlay still finalized
        self.assertIn("q1_operational", result.epistemic_result)
        self.assertEqual(result.finalized_overlay["completion_status"], "FINALIZED")

    @patch("edenfintech_scanner_bootstrap.automation.run_live_scan", side_effect=_mock_live_scan_result)
    @patch("edenfintech_scanner_bootstrap.automation.load_sector_knowledge", side_effect=FileNotFoundError("Not hydrated"))
    def test_missing_sector_knowledge_warns_but_completes(self, mock_sector, mock_live_scan):
        """Missing sector knowledge logs a warning but does not block the flow."""
        from edenfintech_scanner_bootstrap.analyst import ClaudeAnalystClient
        from edenfintech_scanner_bootstrap.validator import RedTeamValidatorClient
        from edenfintech_scanner_bootstrap.epistemic_reviewer import EpistemicReviewerClient

        with self.assertLogs("edenfintech_scanner_bootstrap.automation", level="WARNING") as log:
            result = auto_analyze(
                "RAW1",
                config=self.config,
                out_dir=self.out_dir,
                analyst_client=ClaudeAnalystClient(None, transport=_mock_analyst_transport),
                validator_client=RedTeamValidatorClient("test", transport=_mock_validator_transport_approve),
                epistemic_client=EpistemicReviewerClient("test", transport=_mock_epistemic_transport),
            )

        self.assertIsInstance(result, AutoAnalyzeResult)
        self.assertEqual(result.finalized_overlay["completion_status"], "FINALIZED")
        self.assertTrue(any("sector knowledge" in msg.lower() for msg in log.output))

    @patch("edenfintech_scanner_bootstrap.automation.run_live_scan", side_effect=_mock_live_scan_result)
    def test_finalized_overlay_has_llm_confirmed_provenance(self, mock_live_scan):
        """Finalized overlay has completion_status=FINALIZED and provenance status LLM_CONFIRMED."""
        from edenfintech_scanner_bootstrap.analyst import ClaudeAnalystClient
        from edenfintech_scanner_bootstrap.validator import RedTeamValidatorClient
        from edenfintech_scanner_bootstrap.epistemic_reviewer import EpistemicReviewerClient

        result = auto_analyze(
            "RAW1",
            config=self.config,
            out_dir=self.out_dir,
            analyst_client=ClaudeAnalystClient(None, transport=_mock_analyst_transport),
            validator_client=RedTeamValidatorClient("test", transport=_mock_validator_transport_approve),
            epistemic_client=EpistemicReviewerClient("test", transport=_mock_epistemic_transport),
        )

        overlay = result.finalized_overlay
        self.assertEqual(overlay["completion_status"], "FINALIZED")
        for candidate in overlay["structured_candidates"]:
            for prov in candidate["field_provenance"]:
                self.assertIn(prov["status"], FINAL_PROVENANCE_STATUSES)
                self.assertEqual(prov["status"], "LLM_CONFIRMED")

    @patch("edenfintech_scanner_bootstrap.automation.run_live_scan", side_effect=_mock_live_scan_result)
    def test_epistemic_pcs_answers_replace_analyst_inputs(self, mock_live_scan):
        """Epistemic reviewer PCS answers replace analyst's epistemic_inputs in final overlay."""
        from edenfintech_scanner_bootstrap.analyst import ClaudeAnalystClient
        from edenfintech_scanner_bootstrap.validator import RedTeamValidatorClient
        from edenfintech_scanner_bootstrap.epistemic_reviewer import EpistemicReviewerClient

        result = auto_analyze(
            "RAW1",
            config=self.config,
            out_dir=self.out_dir,
            analyst_client=ClaudeAnalystClient(None, transport=_mock_analyst_transport),
            validator_client=RedTeamValidatorClient("test", transport=_mock_validator_transport_approve),
            epistemic_client=EpistemicReviewerClient("test", transport=_mock_epistemic_transport),
        )

        candidate = result.finalized_overlay["structured_candidates"][0]
        epistemic = candidate["epistemic_inputs"]

        # q4_nonbinary should have the reviewer's "No" answer, not analyst's "Yes"
        self.assertEqual(epistemic["q4_nonbinary"]["answer"], "No")
        self.assertEqual(epistemic["q4_nonbinary"]["justification"], "Outcome is somewhat binary")
        # q1_operational should have reviewer's justification
        self.assertEqual(epistemic["q1_operational"]["justification"], "Operational risk is manageable")

    @patch("edenfintech_scanner_bootstrap.automation.run_live_scan", side_effect=_mock_live_scan_result)
    def test_auto_analyze_result_has_retries_used(self, mock_live_scan):
        """AutoAnalyzeResult contains retries_used count."""
        from edenfintech_scanner_bootstrap.analyst import ClaudeAnalystClient
        from edenfintech_scanner_bootstrap.validator import RedTeamValidatorClient
        from edenfintech_scanner_bootstrap.epistemic_reviewer import EpistemicReviewerClient

        result = auto_analyze(
            "RAW1",
            config=self.config,
            out_dir=self.out_dir,
            analyst_client=ClaudeAnalystClient(None, transport=_mock_analyst_transport),
            validator_client=RedTeamValidatorClient("test", transport=_mock_validator_transport_approve),
            epistemic_client=EpistemicReviewerClient("test", transport=_mock_epistemic_transport),
        )

        self.assertIsInstance(result.retries_used, int)
        self.assertEqual(result.retries_used, 0)
        self.assertIsInstance(result.raw_bundle, dict)


if __name__ == "__main__":
    unittest.main()
