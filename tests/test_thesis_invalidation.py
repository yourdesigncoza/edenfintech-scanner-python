"""Tests for the Thesis Invalidation Module.

Covers hardening gate, field generation, pipeline integration,
and holding review checklist conversion.
"""
from __future__ import annotations

import unittest

from edenfintech_scanner_bootstrap.hardening import detect_thesis_break
from edenfintech_scanner_bootstrap.holding_review import thesis_integrity_checklist
from edenfintech_scanner_bootstrap.validator import PREMORTEM_OUTPUT_SCHEMA


def _condition(
    category: str = "capital_structure",
    risk_description: str = "Debt maturity wall",
    early_warning_metric: str = "Net debt / EBITDA",
    evidence_status: str = "no_current_evidence",
    rationale: str = "Test rationale",
) -> dict:
    return {
        "category": category,
        "risk_description": risk_description,
        "early_warning_metric": early_warning_metric,
        "evidence_status": evidence_status,
        "rationale": rationale,
    }


def _thesis_invalidation(
    conditions: list[dict] | None = None,
    imminent: bool = False,
) -> dict:
    if conditions is None:
        conditions = [_condition()]
    return {
        "conditions": conditions,
        "imminent_break_flag": imminent,
    }


# ---------------------------------------------------------------------------
# Hardening gate: detect_thesis_break
# ---------------------------------------------------------------------------


class TestDetectThesisBreak(unittest.TestCase):
    """Tests for hardening.detect_thesis_break()."""

    def test_none_input_returns_none(self):
        self.assertIsNone(detect_thesis_break(None))

    def test_all_no_evidence_returns_none(self):
        ti = _thesis_invalidation([
            _condition(cat, evidence_status="no_current_evidence")
            for cat in [
                "single_point_failure", "capital_structure",
                "regulatory", "tech_disruption", "market_structure",
            ]
        ])
        self.assertIsNone(detect_thesis_break(ti))

    def test_weak_evidence_returns_watch(self):
        ti = _thesis_invalidation([
            _condition("capital_structure", evidence_status="weak_evidence"),
            _condition("regulatory", evidence_status="no_current_evidence"),
        ])
        result = detect_thesis_break(ti)
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "THESIS_BREAK_WATCH")
        self.assertFalse(result["imminent_break_flag"])
        self.assertEqual(len(result["weak_evidence_conditions"]), 1)

    def test_strong_evidence_returns_imminent(self):
        ti = _thesis_invalidation([
            _condition("capital_structure", evidence_status="strong_evidence"),
            _condition("regulatory", evidence_status="no_current_evidence"),
        ])
        result = detect_thesis_break(ti)
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "THESIS_BREAK_IMMINENT")
        self.assertTrue(result["imminent_break_flag"])
        self.assertEqual(len(result["strong_evidence_conditions"]), 1)

    def test_imminent_flag_true_without_strong_conditions(self):
        """imminent_break_flag=True should trigger even if no conditions
        explicitly have strong_evidence (e.g., flag set by LLM)."""
        ti = _thesis_invalidation(
            [_condition(evidence_status="weak_evidence")],
            imminent=True,
        )
        result = detect_thesis_break(ti)
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "THESIS_BREAK_IMMINENT")

    def test_anti_anchoring_percentage(self):
        ti = _thesis_invalidation([
            _condition(risk_description="15% chance of regulatory ban"),
        ])
        result = detect_thesis_break(ti)
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "THESIS_BREAK_PROBABILITY_ANCHORING")

    def test_anti_anchoring_words(self):
        ti = _thesis_invalidation([
            _condition(risk_description="fifteen percent probability of default"),
        ])
        result = detect_thesis_break(ti)
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "THESIS_BREAK_PROBABILITY_ANCHORING")

    def test_anti_anchoring_decimal(self):
        ti = _thesis_invalidation([
            _condition(risk_description="probability is 0.15"),
        ])
        result = detect_thesis_break(ti)
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "THESIS_BREAK_PROBABILITY_ANCHORING")

    def test_anti_anchoring_in_metric_field(self):
        ti = _thesis_invalidation([
            _condition(early_warning_metric="When probability exceeds 30%"),
        ])
        result = detect_thesis_break(ti)
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "THESIS_BREAK_PROBABILITY_ANCHORING")

    def test_anti_anchoring_fraction(self):
        ti = _thesis_invalidation([
            _condition(risk_description="1 in 5 chance of failure"),
        ])
        result = detect_thesis_break(ti)
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "THESIS_BREAK_PROBABILITY_ANCHORING")

    def test_invalid_evidence_status(self):
        ti = _thesis_invalidation([
            _condition(evidence_status="high_probability"),
        ])
        result = detect_thesis_break(ti)
        self.assertIsNotNone(result)
        self.assertEqual(result["flag"], "THESIS_BREAK_INVALID_STATUS")

    def test_clean_text_not_flagged(self):
        """Normal risk descriptions without probabilities should pass."""
        ti = _thesis_invalidation([
            _condition(
                risk_description="Regulatory ban on core product line",
                early_warning_metric="Pending bill in committee",
                evidence_status="weak_evidence",
            ),
        ])
        result = detect_thesis_break(ti)
        self.assertEqual(result["flag"], "THESIS_BREAK_WATCH")


# ---------------------------------------------------------------------------
# Validator: PreMortem schema
# ---------------------------------------------------------------------------


class TestPreMortemSchema(unittest.TestCase):
    """Verify PREMORTEM_OUTPUT_SCHEMA structure."""

    def test_schema_has_thesis_invalidation(self):
        self.assertIn("thesis_invalidation", PREMORTEM_OUTPUT_SCHEMA["properties"])

    def test_schema_requires_thesis_invalidation(self):
        self.assertIn("thesis_invalidation", PREMORTEM_OUTPUT_SCHEMA["required"])

    def test_conditions_require_rationale(self):
        condition_schema = (
            PREMORTEM_OUTPUT_SCHEMA["properties"]["thesis_invalidation"]
            ["properties"]["conditions"]["items"]
        )
        self.assertIn("rationale", condition_schema["required"])


# ---------------------------------------------------------------------------
# Field generation: _thesis_invalidation_inputs
# ---------------------------------------------------------------------------


class TestFieldGeneration(unittest.TestCase):
    """Tests for field_generation._thesis_invalidation_inputs."""

    def _raw_candidate(self, risk_claims: list[str]) -> dict:
        return {
            "ticker": "TEST",
            "gemini_context": {
                "risk_evidence": [
                    {"claim": c} for c in risk_claims
                ],
            },
        }

    def test_produces_five_conditions(self):
        from edenfintech_scanner_bootstrap.field_generation import _thesis_invalidation_inputs
        raw = self._raw_candidate(["Some general risk"])
        ti, prov = _thesis_invalidation_inputs(raw, "Operational/Financial")
        self.assertEqual(len(ti["conditions"]), 5)
        categories = {c["category"] for c in ti["conditions"]}
        self.assertEqual(categories, {
            "single_point_failure", "capital_structure",
            "regulatory", "tech_disruption", "market_structure",
        })

    def test_never_produces_strong_evidence(self):
        from edenfintech_scanner_bootstrap.field_generation import _thesis_invalidation_inputs
        raw = self._raw_candidate([
            "Single customer concentration risk",
            "Debt covenant breach imminent",
            "Regulatory ban on operations",
            "Technology obsolete",
            "Secular decline in market",
        ])
        ti, prov = _thesis_invalidation_inputs(raw, "Operational/Financial")
        for c in ti["conditions"]:
            self.assertNotEqual(
                c["evidence_status"], "strong_evidence",
                f"MACHINE_DRAFT should never produce strong_evidence (category: {c['category']})",
            )

    def test_keyword_match_produces_weak_evidence(self):
        from edenfintech_scanner_bootstrap.field_generation import _thesis_invalidation_inputs
        raw = self._raw_candidate(["Debt refinancing risk is high"])
        ti, _ = _thesis_invalidation_inputs(raw, "Operational/Financial")
        cap_condition = next(
            c for c in ti["conditions"] if c["category"] == "capital_structure"
        )
        self.assertEqual(cap_condition["evidence_status"], "weak_evidence")

    def test_no_match_produces_no_evidence(self):
        from edenfintech_scanner_bootstrap.field_generation import _thesis_invalidation_inputs
        raw = self._raw_candidate(["Company doing fine"])
        ti, _ = _thesis_invalidation_inputs(raw, "Operational/Financial")
        for c in ti["conditions"]:
            self.assertEqual(
                c["evidence_status"], "no_current_evidence",
                f"Expected no_current_evidence for {c['category']}",
            )

    def test_provenance_count(self):
        from edenfintech_scanner_bootstrap.field_generation import _thesis_invalidation_inputs
        raw = self._raw_candidate(["Some risk"])
        _, prov = _thesis_invalidation_inputs(raw, "Operational/Financial")
        self.assertEqual(len(prov), 6)  # 1 flag + 5 categories


# ---------------------------------------------------------------------------
# Holding review: thesis_integrity_checklist
# ---------------------------------------------------------------------------


class TestThesisIntegrityChecklist(unittest.TestCase):
    """Tests for holding_review.thesis_integrity_checklist."""

    def test_none_returns_empty(self):
        self.assertEqual(thesis_integrity_checklist(None), [])

    def test_converts_conditions_to_checklist(self):
        ti = _thesis_invalidation([
            _condition("capital_structure", evidence_status="no_current_evidence"),
            _condition("regulatory", evidence_status="weak_evidence"),
            _condition("tech_disruption", evidence_status="strong_evidence"),
        ])
        checklist = thesis_integrity_checklist(ti)
        self.assertEqual(len(checklist), 3)
        self.assertEqual(checklist[0]["monitoring_action"], "QUARTERLY_REVIEW")
        self.assertEqual(checklist[1]["monitoring_action"], "MONTHLY_REVIEW")
        self.assertEqual(checklist[2]["monitoring_action"], "IMMEDIATE_REVIEW")

    def test_checklist_includes_early_warning_metric(self):
        ti = _thesis_invalidation([
            _condition(early_warning_metric="Net debt / EBITDA"),
        ])
        checklist = thesis_integrity_checklist(ti)
        self.assertEqual(checklist[0]["early_warning_metric"], "Net debt / EBITDA")

    def test_checklist_preserves_evidence_at_entry(self):
        ti = _thesis_invalidation([
            _condition(evidence_status="weak_evidence"),
        ])
        checklist = thesis_integrity_checklist(ti)
        self.assertEqual(checklist[0]["evidence_status_at_entry"], "weak_evidence")


if __name__ == "__main__":
    unittest.main()
