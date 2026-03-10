"""Tests for the red-team validator agent."""
from __future__ import annotations

import unittest
from copy import deepcopy

from edenfintech_scanner_bootstrap.validator import detect_contradictions


def _make_raw_candidate(
    latest_revenue_b: float = 3.4,
    trough_revenue_b: float = 2.9,
    latest_fcf_margin_pct: float = 10.0,
    shares_m_latest: float = 110.0,
) -> dict:
    """Build a minimal raw candidate with FMP derived data."""
    return {
        "ticker": "TEST1",
        "fmp_context": {
            "derived": {
                "latest_revenue_b": latest_revenue_b,
                "trough_revenue_b": trough_revenue_b,
                "latest_fcf_margin_pct": latest_fcf_margin_pct,
                "shares_m_latest": shares_m_latest,
            }
        },
    }


def _make_overlay_candidate(
    revenue_b: float = 3.4,
    fcf_margin_pct: float = 10.0,
    shares_m: float = 110.0,
) -> dict:
    """Build a minimal overlay candidate with analysis_inputs."""
    return {
        "ticker": "TEST1",
        "analysis_inputs": {
            "base_case_assumptions": {
                "revenue_b": revenue_b,
                "fcf_margin_pct": fcf_margin_pct,
                "shares_m": shares_m,
            },
            "thesis_summary": "Growth expected from improving demand.",
            "margin_trend_gate": "PASS",
        },
    }


class TestContradictionDetection(unittest.TestCase):
    """Tests for detect_contradictions()."""

    def test_high_severity_revenue_gap_over_50pct(self):
        """Revenue > 1.5x FMP latest should flag HIGH."""
        overlay = _make_overlay_candidate(revenue_b=5.5)  # 62% above 3.4
        raw = _make_raw_candidate(latest_revenue_b=3.4)
        contradictions = detect_contradictions(overlay, raw)
        revenue_flags = [c for c in contradictions if c["field"] == "revenue_b"]
        self.assertEqual(len(revenue_flags), 1)
        self.assertEqual(revenue_flags[0]["severity"], "HIGH")

    def test_medium_severity_revenue_gap_10_to_50pct(self):
        """Revenue 10-50% above FMP latest should flag MEDIUM."""
        overlay = _make_overlay_candidate(revenue_b=4.0)  # ~18% above 3.4
        raw = _make_raw_candidate(latest_revenue_b=3.4)
        contradictions = detect_contradictions(overlay, raw)
        revenue_flags = [c for c in contradictions if c["field"] == "revenue_b"]
        self.assertEqual(len(revenue_flags), 1)
        self.assertEqual(revenue_flags[0]["severity"], "MEDIUM")

    def test_fcf_margin_high_severity_over_10pp(self):
        """FCF margin gap > 10pp should flag HIGH."""
        overlay = _make_overlay_candidate(fcf_margin_pct=22.0)  # 12pp above 10.0
        raw = _make_raw_candidate(latest_fcf_margin_pct=10.0)
        contradictions = detect_contradictions(overlay, raw)
        fcf_flags = [c for c in contradictions if c["field"] == "fcf_margin_pct"]
        self.assertEqual(len(fcf_flags), 1)
        self.assertEqual(fcf_flags[0]["severity"], "HIGH")

    def test_fcf_margin_medium_severity_5_to_10pp(self):
        """FCF margin gap 5-10pp should flag MEDIUM."""
        overlay = _make_overlay_candidate(fcf_margin_pct=17.0)  # 7pp above 10.0
        raw = _make_raw_candidate(latest_fcf_margin_pct=10.0)
        contradictions = detect_contradictions(overlay, raw)
        fcf_flags = [c for c in contradictions if c["field"] == "fcf_margin_pct"]
        self.assertEqual(len(fcf_flags), 1)
        self.assertEqual(fcf_flags[0]["severity"], "MEDIUM")

    def test_no_flags_within_thresholds(self):
        """Claims within thresholds (revenue <10%, FCF <5pp, shares <5%) should not flag."""
        overlay = _make_overlay_candidate(revenue_b=3.6, fcf_margin_pct=12.0, shares_m=112.0)
        raw = _make_raw_candidate(latest_revenue_b=3.4, latest_fcf_margin_pct=10.0, shares_m_latest=110.0)
        contradictions = detect_contradictions(overlay, raw)
        self.assertEqual(len(contradictions), 0)

    def test_revenue_direction_contradiction(self):
        """Flag when FMP shows decline (latest < trough) but analyst claims growth."""
        overlay = _make_overlay_candidate(revenue_b=3.0)
        overlay["analysis_inputs"]["thesis_summary"] = "Strong growth trajectory expected."
        raw = _make_raw_candidate(latest_revenue_b=2.5, trough_revenue_b=3.0)
        contradictions = detect_contradictions(overlay, raw)
        direction_flags = [c for c in contradictions if c["field"] == "revenue_direction"]
        self.assertEqual(len(direction_flags), 1)

    def test_share_count_discrepancy_over_5pct(self):
        """Share count > 5% off FMP diluted shares should flag MEDIUM."""
        overlay = _make_overlay_candidate(shares_m=130.0)  # ~18% above 110
        raw = _make_raw_candidate(shares_m_latest=110.0)
        contradictions = detect_contradictions(overlay, raw)
        share_flags = [c for c in contradictions if c["field"] == "shares_m"]
        self.assertEqual(len(share_flags), 1)
        self.assertEqual(share_flags[0]["severity"], "MEDIUM")

    def test_contradiction_dict_keys(self):
        """Each contradiction must have field, claim, actual, severity keys."""
        overlay = _make_overlay_candidate(revenue_b=6.0)
        raw = _make_raw_candidate(latest_revenue_b=3.4)
        contradictions = detect_contradictions(overlay, raw)
        self.assertGreater(len(contradictions), 0)
        for c in contradictions:
            self.assertIn("field", c)
            self.assertIn("claim", c)
            self.assertIn("actual", c)
            self.assertIn("severity", c)

    def test_missing_fmp_derived_graceful_skip(self):
        """Missing fmp_context.derived should return empty list, not error."""
        overlay = _make_overlay_candidate()
        raw = {"ticker": "TEST1", "fmp_context": {}}
        contradictions = detect_contradictions(overlay, raw)
        self.assertEqual(contradictions, [])

    def test_missing_overlay_analysis_inputs_graceful_skip(self):
        """Missing analysis_inputs should return empty list, not error."""
        overlay = {"ticker": "TEST1"}
        raw = _make_raw_candidate()
        contradictions = detect_contradictions(overlay, raw)
        self.assertEqual(contradictions, [])


if __name__ == "__main__":
    unittest.main()
