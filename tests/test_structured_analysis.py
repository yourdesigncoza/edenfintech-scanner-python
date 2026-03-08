from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.assets import load_json
from edenfintech_scanner_bootstrap.structured_analysis import (
    finalize_structured_analysis,
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
    analysis["issues_and_fixes"] = "Reviewed issues and fixes."
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


if __name__ == "__main__":
    unittest.main()
