"""Tests for epistemic reviewer agent with information barrier enforcement."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.epistemic_reviewer import (
    EpistemicReviewInput,
    EpistemicReviewerClient,
    calculate_no_evidence_friction,
    detect_pcs_laundering,
    epistemic_review,
    extract_epistemic_input,
    is_weak_evidence,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reviewer"
_PCS_KEYS = ["q1_operational", "q2_regulatory", "q3_precedent", "q4_nonbinary", "q5_macro"]


def _load_fixture() -> dict:
    return json.loads((_FIXTURE_DIR / "llm-response-fixture.json").read_text())


def _fixture_transport(request_payload: dict) -> dict:
    """Mock transport that returns the fixture LLM response."""
    return {"text": json.dumps(_load_fixture()), "stop_reason": "end_turn"}


def _make_review_input() -> EpistemicReviewInput:
    return EpistemicReviewInput(
        ticker="ACME",
        industry="Industrials",
        thesis_summary="Turnaround with margin recovery and cost restructuring.",
        key_risks=["Execution risk", "Demand weakness"],
        catalysts=["Cost savings program", "Pricing reset"],
        moat_assessment="Switching costs remain meaningful.",
        dominant_risk_type="Operational/Financial",
    )


class TestInformationBarrier(unittest.TestCase):
    """EPST-01: Type-level information barrier enforcement."""

    def test_frozen_dataclass_has_exactly_seven_fields(self) -> None:
        review_input = EpistemicReviewInput(
            ticker="TEST",
            industry="Technology",
            thesis_summary="Turnaround thesis.",
            key_risks=["Execution risk"],
            catalysts=["Cost savings"],
            moat_assessment="Switching costs.",
            dominant_risk_type="Operational/Financial",
        )
        self.assertEqual(len(review_input.__dataclass_fields__), 7)

    def test_rejects_score_kwarg(self) -> None:
        with self.assertRaises(TypeError):
            EpistemicReviewInput(
                ticker="TEST",
                industry="Tech",
                thesis_summary="X",
                key_risks=[],
                catalysts=[],
                moat_assessment="X",
                dominant_risk_type="Operational/Financial",
                score=85.0,
            )

    def test_rejects_probability_kwarg(self) -> None:
        with self.assertRaises(TypeError):
            EpistemicReviewInput(
                ticker="TEST",
                industry="Tech",
                thesis_summary="X",
                key_risks=[],
                catalysts=[],
                moat_assessment="X",
                dominant_risk_type="Operational/Financial",
                probability=70.0,
            )

    def test_rejects_valuation_kwarg(self) -> None:
        with self.assertRaises(TypeError):
            EpistemicReviewInput(
                ticker="TEST",
                industry="Tech",
                thesis_summary="X",
                key_risks=[],
                catalysts=[],
                moat_assessment="X",
                dominant_risk_type="Operational/Financial",
                valuation=100.0,
            )

    def test_rejects_target_price_kwarg(self) -> None:
        with self.assertRaises(TypeError):
            EpistemicReviewInput(
                ticker="TEST",
                industry="Tech",
                thesis_summary="X",
                key_risks=[],
                catalysts=[],
                moat_assessment="X",
                dominant_risk_type="Operational/Financial",
                target_price=55.0,
            )

    def test_rejects_base_case_kwarg(self) -> None:
        with self.assertRaises(TypeError):
            EpistemicReviewInput(
                ticker="TEST",
                industry="Tech",
                thesis_summary="X",
                key_risks=[],
                catalysts=[],
                moat_assessment="X",
                dominant_risk_type="Operational/Financial",
                base_case={"revenue_b": 3.0},
            )

    def test_extract_epistemic_input_drops_numeric_data(self) -> None:
        overlay = {
            "ticker": "ACME",
            "industry": "Industrials",
            "current_price": 25.0,
            "analysis_inputs": {
                "thesis_summary": "Turnaround thesis.",
                "key_risks": ["Demand weakness"],
                "catalysts": ["Cost savings"],
                "moat_assessment": "Brand strength.",
                "dominant_risk_type": "Operational/Financial",
                "base_case_assumptions": {"revenue_b": 3.0},
                "worst_case_assumptions": {"revenue_b": 2.0},
                "probability_inputs": {"base_probability_pct": 70.0},
            },
        }
        result = extract_epistemic_input(overlay)
        self.assertIsInstance(result, EpistemicReviewInput)
        self.assertEqual(result.ticker, "ACME")
        self.assertEqual(result.industry, "Industrials")
        self.assertEqual(result.thesis_summary, "Turnaround thesis.")
        self.assertEqual(result.key_risks, ["Demand weakness"])
        self.assertEqual(result.catalysts, ["Cost savings"])
        self.assertEqual(result.moat_assessment, "Brand strength.")
        self.assertEqual(result.dominant_risk_type, "Operational/Financial")

    def test_extract_has_no_score_or_probability_attributes(self) -> None:
        overlay = {
            "ticker": "ACME",
            "industry": "Industrials",
            "analysis_inputs": {
                "thesis_summary": "X",
                "key_risks": [],
                "catalysts": [],
                "moat_assessment": "X",
                "dominant_risk_type": "Operational/Financial",
                "probability_inputs": {"base_probability_pct": 70.0},
                "base_case_assumptions": {"revenue_b": 3.0, "target_price": 50.0},
            },
        }
        result = extract_epistemic_input(overlay)
        self.assertFalse(hasattr(result, "score"))
        self.assertFalse(hasattr(result, "probability"))
        self.assertFalse(hasattr(result, "base_case_assumptions"))
        self.assertFalse(hasattr(result, "target_price"))
        self.assertFalse(hasattr(result, "current_price"))


class TestEvidenceQuality(unittest.TestCase):
    """EPST-04, EPST-05, EPST-06: Evidence quality detectors."""

    # EPST-04: WEAK_EVIDENCE detection
    def test_weak_evidence_vague_citation(self) -> None:
        self.assertTrue(is_weak_evidence("industry reports suggest growth"))

    def test_weak_evidence_concrete_source(self) -> None:
        self.assertFalse(is_weak_evidence("FY2024 10-K filing page 47"))

    def test_weak_evidence_no_evidence_is_not_weak(self) -> None:
        self.assertFalse(is_weak_evidence("NO_EVIDENCE"))

    def test_weak_evidence_empty_is_not_weak(self) -> None:
        self.assertFalse(is_weak_evidence(""))

    # EPST-05: NO_EVIDENCE friction
    def test_no_evidence_friction_three_triggers_penalty(self) -> None:
        answers = {
            "q1_operational": {"answer": "No", "justification": "X", "evidence": "X", "evidence_source": "NO_EVIDENCE"},
            "q2_regulatory": {"answer": "Yes", "justification": "X", "evidence": "X", "evidence_source": "NO_EVIDENCE"},
            "q3_precedent": {"answer": "No", "justification": "X", "evidence": "X", "evidence_source": "NO_EVIDENCE"},
            "q4_nonbinary": {"answer": "Yes", "justification": "X", "evidence": "X", "evidence_source": "10-K filing"},
            "q5_macro": {"answer": "Yes", "justification": "X", "evidence": "X", "evidence_source": "Earnings call Q3"},
        }
        self.assertEqual(calculate_no_evidence_friction(answers), -1)

    def test_no_evidence_friction_two_no_penalty(self) -> None:
        answers = {
            "q1_operational": {"answer": "No", "justification": "X", "evidence": "X", "evidence_source": "NO_EVIDENCE"},
            "q2_regulatory": {"answer": "Yes", "justification": "X", "evidence": "X", "evidence_source": "NO_EVIDENCE"},
            "q3_precedent": {"answer": "No", "justification": "X", "evidence": "X", "evidence_source": "10-K"},
            "q4_nonbinary": {"answer": "Yes", "justification": "X", "evidence": "X", "evidence_source": "10-K filing"},
            "q5_macro": {"answer": "Yes", "justification": "X", "evidence": "X", "evidence_source": "Earnings call Q3"},
        }
        self.assertEqual(calculate_no_evidence_friction(answers), 0)

    # EPST-06: PCS laundering detection
    def test_laundering_high_overlap(self) -> None:
        analyst_provenance = [
            {"evidence_refs": [{"summary": "10-K filing"}, {"summary": "Earnings call Q3"}]},
            {"evidence_refs": [{"summary": "Investor presentation"}, {"summary": "SEC filing"}, {"summary": "Annual report FY2023"}]},
        ]
        # 5 of 6 unique reviewer sources overlap with analyst = 83.3%
        reviewer_citations = [
            "10-K filing", "Earnings call Q3", "Investor presentation",
            "SEC filing", "Annual report FY2023", "Independent research note",
        ]
        is_laundering, overlap_pct = detect_pcs_laundering(analyst_provenance, reviewer_citations)
        self.assertTrue(is_laundering)
        self.assertGreater(overlap_pct, 80.0)

    def test_laundering_low_overlap(self) -> None:
        analyst_provenance = [
            {"evidence_refs": [{"summary": "10-K filing"}, {"summary": "Earnings call Q3"}]},
        ]
        reviewer_citations = [
            "10-K filing", "Independent research", "Industry analysis", "SEC filing",
        ]
        is_laundering, overlap_pct = detect_pcs_laundering(analyst_provenance, reviewer_citations)
        self.assertFalse(is_laundering)
        self.assertLessEqual(overlap_pct, 80.0)

    def test_laundering_empty_reviewer_sources(self) -> None:
        analyst_provenance = [
            {"evidence_refs": [{"summary": "10-K filing"}]},
        ]
        is_laundering, overlap_pct = detect_pcs_laundering(analyst_provenance, [])
        self.assertTrue(is_laundering)
        self.assertEqual(overlap_pct, 100.0)


class TestEpistemicReview(unittest.TestCase):
    """EPST-02, EPST-03: Client produces 5 PCS answers with evidence anchoring."""

    def setUp(self) -> None:
        self.client = EpistemicReviewerClient(
            api_key="test-key",
            transport=_fixture_transport,
        )
        self.review_input = _make_review_input()

    def test_client_instantiates_with_mock_transport(self) -> None:
        self.assertIsNotNone(self.client)

    def test_review_produces_five_pcs_answers(self) -> None:
        result = self.client.review(self.review_input)
        for key in _PCS_KEYS:
            self.assertIn(key, result, f"Missing PCS key: {key}")
            answer_data = result[key]
            self.assertIn("answer", answer_data)
            self.assertIn("justification", answer_data)
            self.assertIn("evidence", answer_data)
            self.assertIn("evidence_source", answer_data)

    def test_all_answers_are_yes_or_no(self) -> None:
        result = self.client.review(self.review_input)
        for key in _PCS_KEYS:
            self.assertIn(result[key]["answer"], ["Yes", "No"])

    def test_evidence_sources_are_concrete_or_no_evidence(self) -> None:
        result = self.client.review(self.review_input)
        for key in _PCS_KEYS:
            source = result[key]["evidence_source"]
            self.assertTrue(
                isinstance(source, str) and len(source) > 0,
                f"{key} evidence_source must be a non-empty string",
            )

    def test_output_shape_compatible_with_validate_pcs_answers(self) -> None:
        """Output must have q1..q5 each with answer, justification, evidence."""
        result = self.client.review(self.review_input)
        for key in _PCS_KEYS:
            answer_data = result[key]
            self.assertIn(answer_data["answer"], ["Yes", "No"])
            self.assertIsInstance(answer_data["justification"], str)
            self.assertTrue(len(answer_data["justification"]) > 0)
            self.assertIsInstance(answer_data["evidence"], str)
            self.assertTrue(len(answer_data["evidence"]) > 0)

    def test_weak_evidence_detected_in_fixture(self) -> None:
        """Fixture has q3 with vague 'industry reports suggest' citation."""
        result = self.client.review(self.review_input)
        q3_source = result["q3_precedent"]["evidence_source"]
        self.assertTrue(is_weak_evidence(q3_source))

    def test_no_evidence_present_in_fixture(self) -> None:
        """Fixture has q5 with NO_EVIDENCE."""
        result = self.client.review(self.review_input)
        self.assertEqual(result["q5_macro"]["evidence_source"], "NO_EVIDENCE")


class TestEpistemicReviewFlow(unittest.TestCase):
    """Full epistemic_review() call with evidence quality metadata."""

    def setUp(self) -> None:
        self.client = EpistemicReviewerClient(
            api_key="test-key",
            transport=_fixture_transport,
        )
        self.review_input = _make_review_input()

    def test_epistemic_review_returns_weak_evidence_flags(self) -> None:
        result = epistemic_review(self.review_input, client=self.client)
        self.assertIn("weak_evidence_flags", result)
        flags = result["weak_evidence_flags"]
        for key in _PCS_KEYS:
            self.assertIn(key, flags)
        # q3 has vague citation
        self.assertTrue(flags["q3_precedent"])

    def test_epistemic_review_returns_additional_friction(self) -> None:
        result = epistemic_review(self.review_input, client=self.client)
        self.assertIn("additional_friction", result)
        # Fixture has 1 NO_EVIDENCE (q5), so no friction penalty
        self.assertEqual(result["additional_friction"], 0)

    def test_epistemic_review_returns_no_evidence_count(self) -> None:
        result = epistemic_review(self.review_input, client=self.client)
        self.assertIn("no_evidence_count", result)
        self.assertEqual(result["no_evidence_count"], 1)

    def test_epistemic_review_contains_pcs_answers(self) -> None:
        result = epistemic_review(self.review_input, client=self.client)
        for key in _PCS_KEYS:
            self.assertIn(key, result)

    def test_laundering_detection_runs_with_mock_provenance(self) -> None:
        result = epistemic_review(self.review_input, client=self.client)
        # Extract reviewer citations from result
        reviewer_citations = [
            result[key]["evidence_source"]
            for key in _PCS_KEYS
            if result[key]["evidence_source"] != "NO_EVIDENCE"
        ]
        analyst_provenance = [
            {"evidence_refs": [{"summary": "Unrelated source A"}, {"summary": "Unrelated source B"}]},
        ]
        is_laundering, overlap_pct = detect_pcs_laundering(analyst_provenance, reviewer_citations)
        self.assertFalse(is_laundering)


class TestTypeEnforcement(unittest.TestCase):
    """EPST-01: Type enforcement on epistemic_review and client.review."""

    def test_epistemic_review_rejects_non_dataclass(self) -> None:
        client = EpistemicReviewerClient(api_key="test-key", transport=_fixture_transport)
        with self.assertRaises(TypeError):
            epistemic_review({"ticker": "ACME"}, client=client)

    def test_client_review_rejects_non_dataclass(self) -> None:
        client = EpistemicReviewerClient(api_key="test-key", transport=_fixture_transport)
        with self.assertRaises(TypeError):
            client.review({"ticker": "ACME"})

    def test_epistemic_review_rejects_string(self) -> None:
        client = EpistemicReviewerClient(api_key="test-key", transport=_fixture_transport)
        with self.assertRaises(TypeError):
            epistemic_review("not an input", client=client)


if __name__ == "__main__":
    unittest.main()
