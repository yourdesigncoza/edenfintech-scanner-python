from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.assets import load_json
from edenfintech_scanner_bootstrap.structured_analysis import (
    FINAL_PROVENANCE_STATUSES,
    apply_structured_analysis,
    finalize_structured_analysis,
    review_structured_analysis,
    structured_analysis_template,
)


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "raw" / "merged_candidate_bundle.json"


def _review_ready_overlay() -> dict:
    payload = structured_analysis_template(load_json(FIXTURE_PATH))
    candidate = payload["structured_candidates"][0]
    for provenance in candidate["field_provenance"]:
        provenance["review_note"] = f"Reviewer checked {provenance['field_path']} against the fetched evidence."
    candidate["screening_inputs"]["industry_understandable"] = True
    candidate["screening_inputs"]["double_plus_potential"] = True
    for check_name in ["solvency", "dilution", "revenue_growth", "roic", "valuation"]:
        candidate["screening_inputs"][check_name]["verdict"] = "PASS"
        candidate["screening_inputs"][check_name]["evidence"] = f"{check_name} grounded in reviewed evidence."
    analysis = candidate["analysis_inputs"]
    analysis["margin_trend_gate"] = "PASS"
    analysis["final_cluster_status"] = "CLEAR_WINNER"
    analysis["catalyst_classification"] = "VALID_CATALYST"
    analysis["dominant_risk_type"] = "Operational/Financial"
    analysis["catalyst_stack"] = [
        {"type": "HARD", "description": "Pricing reset", "timeline": "Q1 2026"}
    ]
    analysis["invalidation_triggers"] = [
        {"trigger": "Margin erosion resumes", "evidence": "Gross margin drops"}
    ]
    analysis["decision_memo"] = {
        "better_than_peer": "Higher FCF margin",
        "safer_than_peer": "Lower leverage",
        "what_makes_wrong": "Demand decline",
    }
    analysis["issues_and_fixes"] = [
        {"issue": "Plant overcapacity", "fix": "Consolidation", "evidence_status": "ACTION_UNDERWAY"}
    ]
    analysis["setup_pattern"] = "QUALITY_FRANCHISE"
    analysis["stretch_case_assumptions"] = {
        "revenue_b": 4.0,
        "fcf_margin_pct": 12.0,
        "multiple": 24.0,
        "shares_m": 110.0,
        "years": 3.0,
    }
    analysis["moat_assessment"] = "Reviewed moat assessment."
    analysis["thesis_summary"] = "Reviewed thesis summary."
    analysis["catalysts"] = ["Reviewed catalyst"]
    analysis["key_risks"] = ["Reviewed risk"]
    analysis["base_case_assumptions"]["discount_path"] = "Reviewed discount path."
    analysis["probability_inputs"]["base_rate"] = "Reviewed base rate."
    analysis["probability_inputs"]["likert_adjustments"] = "Reviewed likelihood adjustments."
    analysis["exception_candidate"]["reason"] = "No exception required."
    for key in ["q1_operational", "q2_regulatory", "q3_precedent", "q4_nonbinary", "q5_macro"]:
        candidate["epistemic_inputs"][key]["answer"] = "Yes"
        candidate["epistemic_inputs"][key]["justification"] = f"{key} reviewed justification."
        candidate["epistemic_inputs"][key]["evidence"] = f"{key} reviewed evidence."
    return payload


class StructuredAnalysisFinalizationTest(unittest.TestCase):
    def test_finalize_converts_machine_draft_provenance_and_adds_metadata(self) -> None:
        draft = _review_ready_overlay()

        finalized = finalize_structured_analysis(
            draft,
            reviewer="Analyst One",
            note="Analyst review completed.",
        )

        self.assertEqual(finalized["completion_status"], "FINALIZED")
        self.assertEqual(finalized["finalization_metadata"]["reviewer"], "Analyst One")
        self.assertEqual(finalized["finalization_metadata"]["provenance_transition_status"], "HUMAN_CONFIRMED")
        self.assertGreater(finalized["finalization_metadata"]["converted_machine_fields"], 0)
        statuses = {item["status"] for item in finalized["structured_candidates"][0]["field_provenance"]}
        self.assertEqual(statuses, {"HUMAN_CONFIRMED"})
        self.assertEqual(
            finalized["structured_candidates"][0]["analysis_inputs"]["thesis_summary"],
            "Reviewed thesis summary.",
        )

    def test_finalize_rejects_placeholder_overlay(self) -> None:
        draft = structured_analysis_template(load_json(FIXTURE_PATH))

        with self.assertRaisesRegex(ValueError, "still contains placeholder markers"):
            finalize_structured_analysis(draft, reviewer="Analyst One")

    def test_finalize_rejects_internal_fingerprint_mismatch(self) -> None:
        draft = _review_ready_overlay()
        draft["generation_metadata"]["raw_bundle_fingerprint"] = "mismatch"

        with self.assertRaisesRegex(ValueError, "generation metadata fingerprint does not match source_bundle"):
            finalize_structured_analysis(draft, reviewer="Analyst One")

    def test_finalize_rejects_machine_draft_without_review_notes(self) -> None:
        draft = _review_ready_overlay()
        for provenance in draft["structured_candidates"][0]["field_provenance"]:
            provenance.pop("review_note", None)

        with self.assertRaisesRegex(ValueError, "cannot finalize .* without review_note"):
            finalize_structured_analysis(draft, reviewer="Analyst One")


def _llm_draft_overlay() -> dict:
    """Create a review-ready overlay with LLM_DRAFT provenance status."""
    payload = _review_ready_overlay()
    candidate = payload["structured_candidates"][0]
    for provenance in candidate["field_provenance"]:
        provenance["status"] = "LLM_DRAFT"
    return payload


class TestLLMFinalization(unittest.TestCase):
    """Tests for LLM-automated finalization with LLM_CONFIRMED and LLM_EDITED statuses."""

    def test_llm_confirmed_in_final_statuses(self) -> None:
        self.assertIn("LLM_CONFIRMED", FINAL_PROVENANCE_STATUSES)

    def test_llm_edited_in_final_statuses(self) -> None:
        self.assertIn("LLM_EDITED", FINAL_PROVENANCE_STATUSES)

    def test_finalize_with_llm_confirmed_converts_llm_draft(self) -> None:
        draft = _llm_draft_overlay()
        finalized = finalize_structured_analysis(
            draft, reviewer="llm:claude-sonnet-4-5-20250514", final_status="LLM_CONFIRMED",
        )
        self.assertEqual(finalized["completion_status"], "FINALIZED")
        statuses = {item["status"] for item in finalized["structured_candidates"][0]["field_provenance"]}
        self.assertEqual(statuses, {"LLM_CONFIRMED"})
        self.assertEqual(finalized["finalization_metadata"]["provenance_transition_status"], "LLM_CONFIRMED")

    def test_finalize_with_llm_edited_converts_llm_draft(self) -> None:
        draft = _llm_draft_overlay()
        finalized = finalize_structured_analysis(
            draft, reviewer="llm:claude-sonnet-4-5-20250514", final_status="LLM_EDITED",
        )
        statuses = {item["status"] for item in finalized["structured_candidates"][0]["field_provenance"]}
        self.assertEqual(statuses, {"LLM_EDITED"})

    def test_finalize_with_llm_reviewer_format_succeeds(self) -> None:
        draft = _llm_draft_overlay()
        finalized = finalize_structured_analysis(
            draft, reviewer="llm:claude-sonnet-4-5-20250514", final_status="LLM_CONFIRMED",
        )
        self.assertEqual(finalized["finalization_metadata"]["reviewer"], "llm:claude-sonnet-4-5-20250514")

    def test_apply_accepts_llm_confirmed_provenance(self) -> None:
        draft = _llm_draft_overlay()
        finalized = finalize_structured_analysis(
            draft, reviewer="llm:claude-sonnet-4-5-20250514", final_status="LLM_CONFIRMED",
        )
        raw_bundle = load_json(FIXTURE_PATH)
        merged = apply_structured_analysis(raw_bundle, finalized)
        self.assertIn("raw_candidates", merged)

    def test_apply_accepts_llm_edited_provenance(self) -> None:
        draft = _llm_draft_overlay()
        finalized = finalize_structured_analysis(
            draft, reviewer="llm:claude-sonnet-4-5-20250514", final_status="LLM_EDITED",
        )
        raw_bundle = load_json(FIXTURE_PATH)
        merged = apply_structured_analysis(raw_bundle, finalized)
        self.assertIn("raw_candidates", merged)

    def test_review_counts_llm_confirmed_and_llm_edited(self) -> None:
        draft = _llm_draft_overlay()
        finalized = finalize_structured_analysis(
            draft, reviewer="llm:claude-sonnet-4-5-20250514", final_status="LLM_CONFIRMED",
        )
        report = review_structured_analysis(finalized)
        self.assertIn("llm_confirmed", report["summary"])
        self.assertIn("llm_edited", report["summary"])
        self.assertGreater(report["summary"]["llm_confirmed"], 0)
        self.assertEqual(report["summary"]["llm_edited"], 0)


if __name__ == "__main__":
    unittest.main()
