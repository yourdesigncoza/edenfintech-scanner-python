"""Tests for holding_review module -- HOLD-01 through HOLD-05 + integration."""
from __future__ import annotations

import unittest

from edenfintech_scanner_bootstrap.holding_review import (
    FORWARD_HURDLE_PCT,
    MIN_YEARS_REMAINING,
    RAPID_FORWARD_THRESHOLD,
    RAPID_RERATING_THRESHOLD,
    THESIS_STATUSES,
    evaluate_sell_triggers,
    forward_return_refresh,
    fresh_capital_weight,
    replacement_gate,
    review_holding,
    thesis_integrity_check,
)


# -- Shared fixtures ----------------------------------------------------------

BASE_CASE = {
    "revenue_b": 3.0,
    "fcf_margin_pct": 10,
    "multiple": 24,
    "shares_m": 120,
    "years": 3.0,
}

WORST_CASE = {
    "revenue_b": 2.4,
    "fcf_margin_pct": 8,
    "multiple": 12,
    "shares_m": 120,
}

TRIGGERS = [
    {"trigger": "Margin erosion", "evidence": "FCF <5%"},
]

HOLDING = {
    "ticker": "TEST",
    "purchase_price": 25.0,
    "current_weight_pct": 8.5,
    "base_case_assumptions": BASE_CASE,
    "worst_case_assumptions": WORST_CASE,
    "invalidation_triggers": TRIGGERS,
    "effective_probability": 60.0,
    "years_remaining": 2.0,
}


class TestForwardRefresh(unittest.TestCase):
    """HOLD-01: Forward return refresh."""

    def test_basic_refresh(self):
        result = forward_return_refresh(BASE_CASE, current_price=30.0, years_remaining=2.0)
        # target = valuation_target_price(3.0, 10, 24, 120) = 60.0
        self.assertEqual(result["target_price"], 60.0)
        self.assertEqual(result["current_price"], 30.0)
        self.assertAlmostEqual(result["forward_cagr_pct"], 41.42, places=2)
        self.assertEqual(result["years_remaining"], 2.0)

    def test_years_remaining_floored(self):
        result = forward_return_refresh(BASE_CASE, current_price=30.0, years_remaining=0.1)
        self.assertEqual(result["years_remaining"], MIN_YEARS_REMAINING)

    def test_years_remaining_zero(self):
        result = forward_return_refresh(BASE_CASE, current_price=30.0, years_remaining=0.0)
        self.assertEqual(result["years_remaining"], MIN_YEARS_REMAINING)

    def test_years_remaining_negative(self):
        result = forward_return_refresh(BASE_CASE, current_price=30.0, years_remaining=-1.0)
        self.assertEqual(result["years_remaining"], MIN_YEARS_REMAINING)

    def test_at_target_price(self):
        result = forward_return_refresh(BASE_CASE, current_price=60.0, years_remaining=2.0)
        self.assertAlmostEqual(result["forward_cagr_pct"], 0.0, places=2)


class TestThesisIntegrity(unittest.TestCase):
    """HOLD-02: Thesis integrity check."""

    def test_valid_statuses(self):
        self.assertEqual(
            THESIS_STATUSES,
            {"IMPROVED", "DEGRADED", "UNCHANGED", "INVALIDATED"},
        )

    def test_invalidated_trigger(self):
        evidence = [
            {"trigger": "Margin erosion", "status": "INVALIDATED", "evidence": "Q3 FCF margin 2%"},
        ]
        result = thesis_integrity_check(TRIGGERS, evidence)
        self.assertEqual(result["overall_status"], "INVALIDATED")
        self.assertEqual(len(result["assessments"]), 1)
        self.assertEqual(result["assessments"][0]["current_status"], "INVALIDATED")

    def test_no_matching_evidence(self):
        result = thesis_integrity_check(TRIGGERS, [])
        self.assertEqual(result["overall_status"], "UNCHANGED")
        self.assertEqual(result["assessments"][0]["current_status"], "UNCHANGED")

    def test_worst_status_wins(self):
        triggers = [
            {"trigger": "A", "evidence": "e1"},
            {"trigger": "B", "evidence": "e2"},
        ]
        evidence = [
            {"trigger": "A", "status": "IMPROVED", "evidence": "good"},
            {"trigger": "B", "status": "DEGRADED", "evidence": "bad"},
        ]
        result = thesis_integrity_check(triggers, evidence)
        self.assertEqual(result["overall_status"], "DEGRADED")

    def test_severity_ordering(self):
        """INVALIDATED > DEGRADED > UNCHANGED > IMPROVED."""
        triggers = [
            {"trigger": "A", "evidence": "e1"},
            {"trigger": "B", "evidence": "e2"},
            {"trigger": "C", "evidence": "e3"},
        ]
        evidence = [
            {"trigger": "A", "status": "IMPROVED", "evidence": "good"},
            {"trigger": "B", "status": "UNCHANGED", "evidence": "same"},
            {"trigger": "C", "status": "INVALIDATED", "evidence": "bad"},
        ]
        result = thesis_integrity_check(triggers, evidence)
        self.assertEqual(result["overall_status"], "INVALIDATED")


class TestSellTriggers(unittest.TestCase):
    """HOLD-03: Evaluate sell triggers."""

    def _make_refresh(self, current_price, target_price, forward_cagr):
        return {
            "target_price": target_price,
            "current_price": current_price,
            "forward_cagr_pct": forward_cagr,
            "years_remaining": 2.0,
        }

    def _make_thesis(self, overall_status):
        return {"overall_status": overall_status, "assessments": []}

    def test_target_reached_low_forward_fires(self):
        refresh = self._make_refresh(65.0, 60.0, 20.0)
        thesis = self._make_thesis("UNCHANGED")
        triggers = evaluate_sell_triggers(refresh, thesis, purchase_price=25.0)
        names = [t["trigger"] for t in triggers]
        self.assertIn("TARGET_REACHED_LOW_FORWARD", names)

    def test_target_reached_high_forward_no_fire(self):
        refresh = self._make_refresh(65.0, 60.0, 35.0)
        thesis = self._make_thesis("UNCHANGED")
        triggers = evaluate_sell_triggers(refresh, thesis, purchase_price=25.0)
        names = [t["trigger"] for t in triggers]
        self.assertNotIn("TARGET_REACHED_LOW_FORWARD", names)

    def test_rapid_rerating_fires(self):
        # 50%+ gain from purchase=25 -> current must be > 37.5; forward < 15
        refresh = self._make_refresh(40.0, 60.0, 10.0)
        thesis = self._make_thesis("UNCHANGED")
        triggers = evaluate_sell_triggers(refresh, thesis, purchase_price=25.0)
        names = [t["trigger"] for t in triggers]
        self.assertIn("RAPID_RERATING_LOW_FORWARD", names)

    def test_rapid_rerating_exactly_50_no_fire(self):
        # Exactly 50% gain -> NOT > 50%, should not fire
        refresh = self._make_refresh(37.5, 60.0, 10.0)
        thesis = self._make_thesis("UNCHANGED")
        triggers = evaluate_sell_triggers(refresh, thesis, purchase_price=25.0)
        names = [t["trigger"] for t in triggers]
        self.assertNotIn("RAPID_RERATING_LOW_FORWARD", names)

    def test_thesis_break_fires(self):
        refresh = self._make_refresh(30.0, 60.0, 41.42)
        thesis = self._make_thesis("INVALIDATED")
        triggers = evaluate_sell_triggers(refresh, thesis, purchase_price=25.0)
        names = [t["trigger"] for t in triggers]
        self.assertIn("THESIS_BREAK", names)

    def test_no_triggers_fire(self):
        refresh = self._make_refresh(30.0, 60.0, 41.42)
        thesis = self._make_thesis("UNCHANGED")
        triggers = evaluate_sell_triggers(refresh, thesis, purchase_price=25.0)
        self.assertEqual(triggers, [])

    def test_multiple_triggers_fire(self):
        refresh = self._make_refresh(65.0, 60.0, 10.0)
        thesis = self._make_thesis("INVALIDATED")
        triggers = evaluate_sell_triggers(refresh, thesis, purchase_price=25.0)
        names = [t["trigger"] for t in triggers]
        self.assertIn("TARGET_REACHED_LOW_FORWARD", names)
        self.assertIn("RAPID_RERATING_LOW_FORWARD", names)
        self.assertIn("THESIS_BREAK", names)
        self.assertEqual(len(names), 3)


class TestReplacementGate(unittest.TestCase):
    """HOLD-04: Replacement gate."""

    def test_both_gates_pass(self):
        result = replacement_gate(
            holding_forward_cagr=20.0,
            holding_downside_pct=30.0,
            replacement_forward_cagr=40.0,
            replacement_downside_pct=25.0,
        )
        self.assertTrue(result["gate_a_cagr_delta"]["passed"])
        self.assertTrue(result["gate_b_downside"]["passed"])
        self.assertTrue(result["replacement_justified"])

    def test_exactly_15pp_gate_a_fails(self):
        result = replacement_gate(
            holding_forward_cagr=20.0,
            holding_downside_pct=30.0,
            replacement_forward_cagr=35.0,
            replacement_downside_pct=25.0,
        )
        self.assertFalse(result["gate_a_cagr_delta"]["passed"])
        self.assertFalse(result["replacement_justified"])

    def test_gate_b_fails_worse_downside(self):
        result = replacement_gate(
            holding_forward_cagr=20.0,
            holding_downside_pct=30.0,
            replacement_forward_cagr=40.0,
            replacement_downside_pct=35.0,
        )
        self.assertTrue(result["gate_a_cagr_delta"]["passed"])
        self.assertFalse(result["gate_b_downside"]["passed"])
        self.assertFalse(result["replacement_justified"])

    def test_gate_b_equal_downside_passes(self):
        result = replacement_gate(
            holding_forward_cagr=20.0,
            holding_downside_pct=30.0,
            replacement_forward_cagr=40.0,
            replacement_downside_pct=30.0,
        )
        self.assertTrue(result["gate_b_downside"]["passed"])

    def test_delta_pp_value(self):
        result = replacement_gate(
            holding_forward_cagr=20.0,
            holding_downside_pct=30.0,
            replacement_forward_cagr=40.0,
            replacement_downside_pct=25.0,
        )
        self.assertEqual(result["gate_a_cagr_delta"]["delta_pp"], 20.0)


class TestFreshCapitalWeight(unittest.TestCase):
    """HOLD-05: Fresh capital weight computation."""

    def test_returns_band_score_downside(self):
        result = fresh_capital_weight(
            forward_cagr=41.42,
            worst_case=WORST_CASE,
            current_price=30.0,
            effective_probability=60.0,
        )
        self.assertIn("fresh_capital_max_weight", result)
        self.assertIn("score", result)
        self.assertIn("downside_pct", result)
        self.assertIsInstance(result["fresh_capital_max_weight"], str)
        self.assertIsInstance(result["score"], float)

    def test_uses_scoring_pipeline(self):
        """Verify that the result is consistent with scoring.py functions."""
        from edenfintech_scanner_bootstrap.scoring import (
            decision_score,
            downside_pct,
            floor_price,
            score_to_size_band,
        )

        floor_val = floor_price(
            WORST_CASE["revenue_b"],
            WORST_CASE["fcf_margin_pct"],
            WORST_CASE["multiple"],
            WORST_CASE["shares_m"],
        )
        ds = downside_pct(30.0, floor_val)
        score = decision_score(ds, 60.0, 41.42)
        band = score_to_size_band(score.total_score)

        result = fresh_capital_weight(41.42, WORST_CASE, 30.0, 60.0)
        self.assertEqual(result["fresh_capital_max_weight"], band)
        self.assertEqual(result["score"], score.total_score)
        self.assertEqual(result["downside_pct"], ds)


class TestReviewHolding(unittest.TestCase):
    """Integration: review_holding assembles all components."""

    def test_basic_review(self):
        result = review_holding(HOLDING, current_price=30.0)
        self.assertEqual(result["ticker"], "TEST")
        self.assertIn("forward_refresh", result)
        self.assertIn("thesis_integrity", result)
        self.assertIn("sell_triggers", result)
        self.assertIn("sell_triggered", result)
        self.assertIn("fresh_capital_assessment", result)
        self.assertIn("current_weight_pct", result)
        self.assertFalse(result["sell_triggered"])

    def test_no_replacement_gate_by_default(self):
        result = review_holding(HOLDING, current_price=30.0)
        self.assertNotIn("replacement_gate", result)

    def test_with_replacement_candidate(self):
        candidate = {"forward_cagr_pct": 60.0, "downside_pct": 20.0}
        result = review_holding(HOLDING, current_price=30.0, replacement_candidate=candidate)
        self.assertIn("replacement_gate", result)
        self.assertTrue(result["replacement_gate"]["replacement_justified"])

    def test_sell_triggered_flag(self):
        # Use a price at target with low forward -> triggers fire
        holding = {**HOLDING, "years_remaining": 2.0}
        result = review_holding(holding, current_price=60.0)
        self.assertTrue(result["sell_triggered"])

    def test_current_evidence_flows_to_thesis(self):
        holding = {
            **HOLDING,
            "current_evidence": [
                {"trigger": "Margin erosion", "status": "DEGRADED", "evidence": "FCF 4%"},
            ],
        }
        result = review_holding(holding, current_price=30.0)
        self.assertEqual(result["thesis_integrity"]["overall_status"], "DEGRADED")


if __name__ == "__main__":
    unittest.main()
