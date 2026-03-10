"""Tests for epistemic reviewer agent with information barrier enforcement."""
from __future__ import annotations

import unittest

from edenfintech_scanner_bootstrap.epistemic_reviewer import (
    EpistemicReviewInput,
    calculate_no_evidence_friction,
    detect_pcs_laundering,
    extract_epistemic_input,
    is_weak_evidence,
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


if __name__ == "__main__":
    unittest.main()
