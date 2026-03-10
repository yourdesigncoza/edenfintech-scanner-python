from __future__ import annotations

import json
import os
import unittest
from copy import deepcopy
from pathlib import Path

from edenfintech_scanner_bootstrap.assets import load_json
from edenfintech_scanner_bootstrap.structured_analysis import (
    DRAFT_PROVENANCE_STATUSES,
    REQUIRED_PROVENANCE_FIELDS,
    finalize_structured_analysis,
    validate_structured_analysis,
)
from edenfintech_scanner_bootstrap.config import AppConfig, load_config


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "raw" / "merged_candidate_bundle.json"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "assets" / "methodology" / "structured-analysis.schema.json"


class TestLlmDraftProvenanceStatus(unittest.TestCase):
    """Tests for LLM_DRAFT provenance lifecycle."""

    def test_llm_draft_accepted_in_schema_validation(self):
        """LLM_DRAFT is accepted by the structured-analysis schema for field_provenance.status."""
        schema = load_json(SCHEMA_PATH)
        status_enum = schema["definitions"]["field_provenance"]["properties"]["status"]["enum"]
        self.assertIn("LLM_DRAFT", status_enum)

    def test_draft_provenance_statuses_includes_both(self):
        """DRAFT_PROVENANCE_STATUSES contains both MACHINE_DRAFT and LLM_DRAFT."""
        self.assertIn("MACHINE_DRAFT", DRAFT_PROVENANCE_STATUSES)
        self.assertIn("LLM_DRAFT", DRAFT_PROVENANCE_STATUSES)

    def test_finalize_transitions_llm_draft(self):
        """finalize_structured_analysis transitions LLM_DRAFT entries to final_status."""
        overlay = self._llm_draft_overlay()
        finalized = finalize_structured_analysis(overlay, reviewer="test-reviewer")
        for item in finalized["structured_candidates"][0]["field_provenance"]:
            self.assertNotEqual(item["status"], "LLM_DRAFT",
                                f"LLM_DRAFT not transitioned for {item['field_path']}")
            self.assertEqual(item["status"], "HUMAN_CONFIRMED")

    def test_finalize_refuses_llm_draft_without_review_note(self):
        """finalize_structured_analysis refuses LLM_DRAFT entries without review_note."""
        overlay = self._llm_draft_overlay()
        # Remove review_note from first provenance entry
        overlay["structured_candidates"][0]["field_provenance"][0].pop("review_note", None)
        with self.assertRaises(ValueError):
            finalize_structured_analysis(overlay, reviewer="test-reviewer")

    def test_validate_provenance_coverage_rejects_llm_draft_when_not_allowed(self):
        """_validate_provenance_coverage rejects LLM_DRAFT when allow_machine_draft=False."""
        from edenfintech_scanner_bootstrap.structured_analysis import _validate_provenance_coverage
        overlay = self._llm_draft_overlay()
        candidate = overlay["structured_candidates"][0]
        with self.assertRaises(ValueError) as ctx:
            _validate_provenance_coverage(
                candidate,
                allow_machine_draft=False,
                require_review_note_for_finalized=False,
            )
        self.assertIn("LLM_DRAFT", str(ctx.exception))

    def _llm_draft_overlay(self) -> dict:
        """Build a valid structured analysis overlay with LLM_DRAFT provenance."""
        from edenfintech_scanner_bootstrap.structured_analysis import (
            structured_analysis_template,
            _candidate_evidence_context,
            _fingerprint,
            _raw_bundle_fingerprint,
        )
        raw_bundle = load_json(FIXTURE_PATH)
        payload = structured_analysis_template(raw_bundle)
        candidate = payload["structured_candidates"][0]
        raw_candidate = raw_bundle["raw_candidates"][0]

        # Set all provenance to LLM_DRAFT with review_notes
        for item in candidate["field_provenance"]:
            item["status"] = "LLM_DRAFT"
            item["review_note"] = f"LLM assessed {item['field_path']} citing Earnings call evidence."

        # Fill all placeholders
        candidate["screening_inputs"]["industry_understandable"] = True
        candidate["screening_inputs"]["double_plus_potential"] = True
        for check_name in ["solvency", "dilution", "revenue_growth", "roic", "valuation"]:
            candidate["screening_inputs"][check_name] = {"verdict": "PASS", "evidence": "LLM evidence"}
        ai = candidate["analysis_inputs"]
        ai["margin_trend_gate"] = "PASS"
        ai["final_cluster_status"] = "CLEAR_WINNER"
        ai["catalyst_classification"] = "VALID_CATALYST"
        ai["dominant_risk_type"] = "Operational/Financial"
        ai["catalyst_stack"] = [{"type": "HARD", "description": "Pricing", "timeline": "Q1 2026"}]
        ai["invalidation_triggers"] = [{"trigger": "Margin erosion", "evidence": "Margin drops"}]
        ai["decision_memo"] = {"better_than_peer": "FCF", "safer_than_peer": "Leverage", "what_makes_wrong": "Demand"}
        ai["issues_and_fixes"] = [{"issue": "Plant", "fix": "Consolidation", "evidence_status": "ACTION_UNDERWAY"}]
        ai["setup_pattern"] = "QUALITY_FRANCHISE"
        ai["stretch_case_assumptions"] = {"revenue_b": 4.0, "fcf_margin_pct": 12.0, "multiple": 24.0, "shares_m": 110.0, "years": 3.0, "discount_path": "Full recovery"}
        ai["moat_assessment"] = "Sticky customers"
        ai["thesis_summary"] = "Turnaround with pricing catalyst"
        ai["catalysts"] = ["Pricing reset"]
        ai["key_risks"] = ["Plant consolidation risk"]
        ai["base_case_assumptions"] = {"revenue_b": 3.4, "fcf_margin_pct": 10.0, "multiple": 20.0, "shares_m": 110.0, "years": 3.0, "discount_path": "Current margin"}
        ai["worst_case_assumptions"] = {"revenue_b": 2.9, "fcf_margin_pct": 7.0, "multiple": 12.0, "shares_m": 110.0}
        ai["probability_inputs"] = {"base_probability_pct": 70.0, "base_rate": "Good FCF", "likert_adjustments": "Neutral"}
        ai["exception_candidate"] = {"eligible": False, "reason": "Not applicable"}
        for key in ["q1_operational", "q2_regulatory", "q3_precedent", "q4_nonbinary", "q5_macro"]:
            candidate["epistemic_inputs"][key] = {"answer": "Yes", "justification": "LLM assessed", "evidence": "Source"}

        return payload


class TestAppConfigAnthropicFields(unittest.TestCase):
    """Tests for Anthropic API key and analyst model config fields."""

    def test_appconfig_has_anthropic_api_key(self):
        config = AppConfig(
            fmp_api_key=None,
            gemini_api_key=None,
            openai_api_key=None,
            codex_judge_model="gpt-5-codex",
            anthropic_api_key="sk-test-123",
            analyst_model="claude-sonnet-4-5-20250514",
        )
        self.assertEqual(config.anthropic_api_key, "sk-test-123")

    def test_appconfig_has_analyst_model(self):
        config = AppConfig(
            fmp_api_key=None,
            gemini_api_key=None,
            openai_api_key=None,
            codex_judge_model="gpt-5-codex",
            anthropic_api_key=None,
            analyst_model="claude-sonnet-4-5-20250514",
        )
        self.assertEqual(config.analyst_model, "claude-sonnet-4-5-20250514")

    def test_load_config_reads_anthropic_env_vars(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-env-test"
        os.environ["ANALYST_MODEL"] = "claude-opus-4-20250514"
        try:
            config = load_config()
            self.assertEqual(config.anthropic_api_key, "sk-env-test")
            self.assertEqual(config.analyst_model, "claude-opus-4-20250514")
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("ANALYST_MODEL", None)

    def test_load_config_analyst_model_default(self):
        os.environ.pop("ANALYST_MODEL", None)
        config = load_config()
        self.assertEqual(config.analyst_model, "claude-sonnet-4-5-20250514")


if __name__ == "__main__":
    unittest.main()
