"""Tests for the red-team validator agent."""
from __future__ import annotations

import unittest
from copy import deepcopy

from edenfintech_scanner_bootstrap.validator import (
    RedTeamValidatorClient,
    detect_contradictions,
    validate_overlay,
)

import json
from pathlib import Path

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "validator"


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


def _load_reject_fixture() -> dict:
    """Load the REJECT LLM response fixture."""
    return json.loads((_FIXTURE_DIR / "llm-response-fixture.json").read_text())


def _make_approve_fixture() -> dict:
    """Build an APPROVE variant with empty objections."""
    fixture = _load_reject_fixture()
    fixture["verdict"] = "APPROVE"
    fixture["objections"] = []
    return fixture


def _fixture_transport(fixture_data: dict):
    """Return a transport function that captures request and returns fixture."""
    captured_requests = []

    def transport(request_payload: dict) -> dict:
        captured_requests.append(request_payload)
        return {"text": json.dumps(fixture_data), "stop_reason": "end_turn"}

    transport.captured_requests = captured_requests
    return transport


class TestRedTeamValidator(unittest.TestCase):
    """Tests for RedTeamValidatorClient."""

    def test_instantiates_with_mock_transport(self):
        """Client should accept a mock transport."""
        transport = _fixture_transport(_load_reject_fixture())
        client = RedTeamValidatorClient("fake-key", transport=transport)
        self.assertIsNotNone(client)

    def test_validate_returns_required_keys(self):
        """validate() result must have verdict, questions, objections, contradictions."""
        fixture = _load_reject_fixture()
        transport = _fixture_transport(fixture)
        client = RedTeamValidatorClient("fake-key", transport=transport)
        overlay = _make_overlay_candidate()
        raw = _make_raw_candidate()
        result = client.validate(overlay, raw, [])
        for key in ("verdict", "questions", "objections", "contradictions"):
            self.assertIn(key, result)

    def test_fixture_produces_5_questions(self):
        """Fixture should produce exactly 5 questions with required keys."""
        fixture = _load_reject_fixture()
        transport = _fixture_transport(fixture)
        client = RedTeamValidatorClient("fake-key", transport=transport)
        overlay = _make_overlay_candidate()
        raw = _make_raw_candidate()
        result = client.validate(overlay, raw, [])
        self.assertEqual(len(result["questions"]), 5)
        for q in result["questions"]:
            self.assertIn("question_id", q)
            self.assertIn("challenge", q)
            self.assertIn("evidence", q)
            self.assertIn("severity", q)

    def test_reject_verdict_has_nonempty_objections(self):
        """REJECT verdict must include non-empty objections array."""
        fixture = _load_reject_fixture()
        transport = _fixture_transport(fixture)
        client = RedTeamValidatorClient("fake-key", transport=transport)
        result = client.validate(_make_overlay_candidate(), _make_raw_candidate(), [])
        self.assertEqual(result["verdict"], "REJECT")
        self.assertGreater(len(result["objections"]), 0)

    def test_approve_verdict_has_empty_objections(self):
        """APPROVE verdict must have empty objections array."""
        fixture = _make_approve_fixture()
        transport = _fixture_transport(fixture)
        client = RedTeamValidatorClient("fake-key", transport=transport)
        result = client.validate(_make_overlay_candidate(), _make_raw_candidate(), [])
        self.assertEqual(result["verdict"], "APPROVE")
        self.assertEqual(result["objections"], [])

    def test_contradictions_included_in_request_payload(self):
        """Pre-computed contradictions must appear in the request payload."""
        fixture = _load_reject_fixture()
        transport = _fixture_transport(fixture)
        client = RedTeamValidatorClient("fake-key", transport=transport)
        test_contradictions = [{"field": "revenue_b", "claim": "5.0", "actual": "3.4", "severity": "HIGH"}]
        client.validate(_make_overlay_candidate(), _make_raw_candidate(), test_contradictions)
        self.assertEqual(len(transport.captured_requests), 1)
        payload_text = json.dumps(transport.captured_requests[0])
        self.assertIn("revenue_b", payload_text)
        self.assertIn("5.0", payload_text)

    def test_request_payload_excludes_scores(self):
        """Request payload must NOT contain pipeline scores or rankings."""
        fixture = _load_reject_fixture()
        transport = _fixture_transport(fixture)
        client = RedTeamValidatorClient("fake-key", transport=transport)
        overlay = _make_overlay_candidate()
        # Add score fields that should NOT leak into validator
        overlay["decision_score"] = 85.0
        overlay["total_score"] = 92.0
        overlay["ranking"] = 1
        overlay["effective_probability"] = 75.0
        client.validate(overlay, _make_raw_candidate(), [])
        payload_text = json.dumps(transport.captured_requests[0])
        for forbidden in ("decision_score", "total_score", "ranking", "effective_probability"):
            self.assertNotIn(forbidden, payload_text)


class TestValidateOverlayFlow(unittest.TestCase):
    """Tests for the top-level validate_overlay() function."""

    def test_validate_overlay_returns_all_keys(self):
        """validate_overlay() must return verdict, questions, objections, contradictions."""
        fixture = _load_reject_fixture()
        transport = _fixture_transport(fixture)
        client = RedTeamValidatorClient("fake-key", transport=transport)
        overlay = _make_overlay_candidate(revenue_b=6.0)  # will produce contradictions
        raw = _make_raw_candidate(latest_revenue_b=3.4)
        result = validate_overlay(overlay, raw, client=client)
        for key in ("verdict", "questions", "objections", "contradictions"):
            self.assertIn(key, result)

    def test_contradictions_run_first_and_appear_in_output(self):
        """Contradictions from detect_contradictions should appear in the final result."""
        fixture = _load_reject_fixture()
        transport = _fixture_transport(fixture)
        client = RedTeamValidatorClient("fake-key", transport=transport)
        overlay = _make_overlay_candidate(revenue_b=6.0)  # >50% gap -> HIGH
        raw = _make_raw_candidate(latest_revenue_b=3.4)
        result = validate_overlay(overlay, raw, client=client)
        self.assertGreater(len(result["contradictions"]), 0)
        revenue_flags = [c for c in result["contradictions"] if c["field"] == "revenue_b"]
        self.assertEqual(len(revenue_flags), 1)

    def test_request_excludes_scores_in_full_flow(self):
        """Full flow should not leak pipeline scores into the request payload."""
        fixture = _load_reject_fixture()
        transport = _fixture_transport(fixture)
        client = RedTeamValidatorClient("fake-key", transport=transport)
        overlay = _make_overlay_candidate()
        overlay["decision_score"] = 99.0
        raw = _make_raw_candidate()
        validate_overlay(overlay, raw, client=client)
        payload_text = json.dumps(transport.captured_requests[0])
        self.assertNotIn("decision_score", payload_text)


if __name__ == "__main__":
    unittest.main()
