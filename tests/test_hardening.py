"""Tests for hardening gates: probability anchoring, evidence quality, CAGR exception panel."""
from __future__ import annotations

import json
import unittest


class TestProbabilityAnchoring(unittest.TestCase):
    """Tests for detect_probability_anchoring."""

    def test_flags_60_pct_with_cyclical_macro(self):
        from edenfintech_scanner_bootstrap.hardening import detect_probability_anchoring

        result = detect_probability_anchoring(60.0, "Cyclical/Macro")
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "PROBABILITY_ANCHORING_SUSPECT")
        self.assertEqual(result["base_probability_pct"], 60.0)
        self.assertEqual(result["dominant_risk_type"], "Cyclical/Macro")
        self.assertIn("reason", result)

    def test_flags_60_pct_with_regulatory_political(self):
        from edenfintech_scanner_bootstrap.hardening import detect_probability_anchoring

        result = detect_probability_anchoring(60.0, "Regulatory/Political")
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "PROBABILITY_ANCHORING_SUSPECT")

    def test_flags_60_pct_with_legal_investigation(self):
        from edenfintech_scanner_bootstrap.hardening import detect_probability_anchoring

        result = detect_probability_anchoring(60.0, "Legal/Investigation")
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "PROBABILITY_ANCHORING_SUSPECT")

    def test_flags_60_pct_with_structural_fragility(self):
        from edenfintech_scanner_bootstrap.hardening import detect_probability_anchoring

        result = detect_probability_anchoring(60.0, "Structural fragility (SPOF)")
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "PROBABILITY_ANCHORING_SUSPECT")

    def test_returns_none_for_60_pct_non_friction_risk(self):
        from edenfintech_scanner_bootstrap.hardening import detect_probability_anchoring

        result = detect_probability_anchoring(60.0, "Competitive/Secular")
        self.assertIsNone(result)

    def test_returns_none_for_non_60_probability(self):
        from edenfintech_scanner_bootstrap.hardening import detect_probability_anchoring

        self.assertIsNone(detect_probability_anchoring(55.0, "Cyclical/Macro"))
        self.assertIsNone(detect_probability_anchoring(65.0, "Regulatory/Political"))
        self.assertIsNone(detect_probability_anchoring(59.9, "Legal/Investigation"))
        self.assertIsNone(detect_probability_anchoring(60.1, "Cyclical/Macro"))


class TestEvidenceQuality(unittest.TestCase):
    """Tests for score_evidence_quality."""

    def _make_overlay(self, review_notes: list[str]) -> dict:
        """Build minimal overlay with provenance entries."""
        return {
            "provenance": [
                {"field": f"field_{i}", "review_note": note}
                for i, note in enumerate(review_notes)
            ],
        }

    def test_counts_concrete_citations(self):
        from edenfintech_scanner_bootstrap.hardening import score_evidence_quality

        overlay = self._make_overlay([
            "Confirmed via 10-K FY2024 filing",
            "Verified from Q3 earnings call transcript",
            "Cross-checked with SEC filing from 2023",
        ])
        result = score_evidence_quality(overlay)
        self.assertEqual(result["total_citations"], 3)
        self.assertEqual(result["concrete_count"], 3)
        self.assertEqual(result["vague_count"], 0)
        self.assertEqual(result["concrete_ratio"], 1.0)
        self.assertIsNone(result["methodology_warning"])

    def test_warns_below_threshold(self):
        from edenfintech_scanner_bootstrap.hardening import score_evidence_quality

        overlay = self._make_overlay([
            "Industry reports suggest growth",
            "Various sources confirm trend",
            "Confirmed via 10-K FY2024 filing",
        ])
        result = score_evidence_quality(overlay)
        self.assertEqual(result["total_citations"], 3)
        self.assertEqual(result["concrete_count"], 1)
        self.assertEqual(result["vague_count"], 2)
        self.assertAlmostEqual(result["concrete_ratio"], 1 / 3)
        self.assertIsNotNone(result["methodology_warning"])
        self.assertIn("concrete", result["methodology_warning"].lower())

    def test_no_warning_at_threshold(self):
        from edenfintech_scanner_bootstrap.hardening import score_evidence_quality

        overlay = self._make_overlay([
            "Confirmed via 10-K FY2024",
            "Various sources confirm trend",
        ])
        result = score_evidence_quality(overlay)
        self.assertEqual(result["concrete_ratio"], 0.5)
        self.assertIsNone(result["methodology_warning"])

    def test_empty_provenance(self):
        from edenfintech_scanner_bootstrap.hardening import score_evidence_quality

        overlay = {"provenance": []}
        result = score_evidence_quality(overlay)
        self.assertEqual(result["total_citations"], 0)
        self.assertEqual(result["concrete_count"], 0)
        self.assertEqual(result["vague_count"], 0)
        self.assertEqual(result["concrete_ratio"], 0.0)
        self.assertIsNone(result["methodology_warning"])

    def test_missing_provenance_key(self):
        from edenfintech_scanner_bootstrap.hardening import score_evidence_quality

        result = score_evidence_quality({})
        self.assertEqual(result["total_citations"], 0)
        self.assertEqual(result["concrete_ratio"], 0.0)


class TestCagrExceptionPanel(unittest.TestCase):
    """Tests for cagr_exception_panel with 3-agent unanimous vote."""

    SAMPLE_OVERLAY = {
        "ticker": "ACME",
        "analysis_inputs": {
            "thesis_summary": "Turnaround play with strong FCF generation",
            "catalyst_stack": [
                {"catalyst": "New CEO with proven track record"},
            ],
            "key_risks": ["Cyclical demand exposure", "High leverage"],
            "base_case_assumptions": {"cagr_pct": 25.0},
        },
    }

    SAMPLE_RAW = {
        "ticker": "ACME",
        "revenue": [100, 110, 120],
    }

    def _make_transport(self, approve: bool, reasoning: str = "Test reasoning"):
        """Return a mock transport that returns a canned vote."""
        def transport(payload: dict) -> dict:
            return {
                "text": json.dumps({"approve": approve, "reasoning": reasoning}),
                "stop_reason": "end_turn",
            }
        return transport

    def test_all_approve_returns_approved_unanimous(self):
        from edenfintech_scanner_bootstrap.hardening import cagr_exception_panel

        result = cagr_exception_panel(
            self.SAMPLE_OVERLAY,
            self.SAMPLE_RAW,
            analyst_transport=self._make_transport(True, "Strong FCF supports exception"),
            validator_transport=self._make_transport(True, "Evidence is solid"),
            epistemic_transport=self._make_transport(True, "Precedent exists"),
        )
        self.assertTrue(result.approved)
        self.assertTrue(result.unanimous)
        self.assertEqual(len(result.votes), 3)

    def test_one_reject_returns_not_approved(self):
        from edenfintech_scanner_bootstrap.hardening import cagr_exception_panel

        result = cagr_exception_panel(
            self.SAMPLE_OVERLAY,
            self.SAMPLE_RAW,
            analyst_transport=self._make_transport(True),
            validator_transport=self._make_transport(False, "Insufficient evidence"),
            epistemic_transport=self._make_transport(True),
        )
        self.assertFalse(result.approved)
        self.assertFalse(result.unanimous)

    def test_all_reject_returns_not_approved_unanimous(self):
        from edenfintech_scanner_bootstrap.hardening import cagr_exception_panel

        result = cagr_exception_panel(
            self.SAMPLE_OVERLAY,
            self.SAMPLE_RAW,
            analyst_transport=self._make_transport(False),
            validator_transport=self._make_transport(False),
            epistemic_transport=self._make_transport(False),
        )
        self.assertFalse(result.approved)
        self.assertTrue(result.unanimous)

    def test_votes_contain_agent_name_and_fields(self):
        from edenfintech_scanner_bootstrap.hardening import cagr_exception_panel

        result = cagr_exception_panel(
            self.SAMPLE_OVERLAY,
            self.SAMPLE_RAW,
            analyst_transport=self._make_transport(True, "Analyst approves"),
            validator_transport=self._make_transport(False, "Validator rejects"),
            epistemic_transport=self._make_transport(True, "Epistemic approves"),
        )
        agent_names = {v.agent for v in result.votes}
        self.assertEqual(agent_names, {"analyst", "validator", "epistemic"})
        for vote in result.votes:
            self.assertIsInstance(vote.agent, str)
            self.assertIsInstance(vote.approve, bool)
            self.assertIsInstance(vote.reasoning, str)
            self.assertTrue(len(vote.reasoning) > 0)

    def test_result_has_exactly_3_votes(self):
        from edenfintech_scanner_bootstrap.hardening import cagr_exception_panel

        result = cagr_exception_panel(
            self.SAMPLE_OVERLAY,
            self.SAMPLE_RAW,
            analyst_transport=self._make_transport(True),
            validator_transport=self._make_transport(True),
            epistemic_transport=self._make_transport(True),
        )
        self.assertEqual(len(result.votes), 3)


if __name__ == "__main__":
    unittest.main()
