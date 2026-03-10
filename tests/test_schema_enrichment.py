"""Tests for enriched scan-input and structured-analysis schema fields.

Covers: catalyst_stack, invalidation_triggers, decision_memo,
issues_and_fixes (array), setup_pattern, stretch_case.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.assets import scan_input_schema_path
from edenfintech_scanner_bootstrap.schemas import SchemaValidationError, validate_instance


def _load_scan_input_schema() -> dict:
    return json.loads(scan_input_schema_path().read_text())


def _minimal_candidate(**overrides) -> dict:
    """Return a minimal candidate that passes screening + has all analysis fields."""
    candidate = {
        "ticker": "TST",
        "cluster_name": "test-cluster",
        "industry": "Test Industry",
        "current_price": 25.0,
        "screening": {
            "pct_off_ath": 72.0,
            "industry_understandable": True,
            "industry_in_secular_decline": False,
            "double_plus_potential": True,
            "checks": {
                "solvency": {"verdict": "PASS", "note": "ok"},
                "dilution": {"verdict": "PASS", "note": "ok"},
                "revenue_growth": {"verdict": "PASS", "note": "ok"},
                "roic": {"verdict": "PASS", "note": "ok"},
                "valuation": {"verdict": "PASS", "note": "ok"},
            },
        },
        "analysis": {
            "margin_trend_gate": "PASS",
            "final_cluster_status": "CLEAR_WINNER",
            "catalyst_classification": "VALID_CATALYST",
            "dominant_risk_type": "Operational/Financial",
            "base_case": {
                "revenue_b": 3.0,
                "fcf_margin_pct": 10.0,
                "multiple": 24.0,
                "shares_m": 120.0,
                "years": 3.0,
            },
            "worst_case": {
                "revenue_b": 2.4,
                "fcf_margin_pct": 8.0,
                "multiple": 12.0,
                "shares_m": 120.0,
            },
            "probability": {"base_probability_pct": 68.0},
            "catalyst_stack": [
                {"type": "HARD", "description": "Pricing reset", "timeline": "Q1 2026"}
            ],
            "invalidation_triggers": [
                {"trigger": "CEO departure", "evidence": "Board instability"}
            ],
            "decision_memo": {
                "better_than_peer": "Stronger margins than peers",
                "safer_than_peer": "Lower leverage ratio",
                "what_makes_wrong": "Demand decline",
            },
            "issues_and_fixes": [
                {
                    "issue": "Plant overcapacity",
                    "fix": "Consolidation underway",
                    "evidence_status": "ACTION_UNDERWAY",
                }
            ],
            "setup_pattern": "QUALITY_FRANCHISE",
            "stretch_case": {
                "revenue_b": 4.0,
                "fcf_margin_pct": 12.0,
                "multiple": 28.0,
                "shares_m": 120.0,
                "years": 3.0,
            },
        },
        "epistemic_review": {
            "q1_operational": {"answer": "Yes", "justification": "j", "evidence": "e"},
            "q2_regulatory": {"answer": "Yes", "justification": "j", "evidence": "e"},
            "q3_precedent": {"answer": "Yes", "justification": "j", "evidence": "e"},
            "q4_nonbinary": {"answer": "Yes", "justification": "j", "evidence": "e"},
            "q5_macro": {"answer": "Yes", "justification": "j", "evidence": "e"},
        },
    }
    for key, value in overrides.items():
        candidate["analysis"][key] = value
    return candidate


def _valid_payload(candidate: dict) -> dict:
    return {
        "scan_parameters": {"scan_mode": "specific_tickers", "focus": "TST"},
        "candidates": [candidate],
    }


def _validate(payload: dict) -> None:
    schema = _load_scan_input_schema()
    validate_instance(payload, schema)


class TestSchemaEnrichment(unittest.TestCase):
    """Schema validation tests for the 6 new Codex field groups."""

    # -- catalyst_stack --

    def test_catalyst_stack_valid(self) -> None:
        candidate = _minimal_candidate(
            catalyst_stack=[
                {"type": "HARD", "description": "Price increase", "timeline": "Q1 2026"},
                {"type": "MEDIUM", "description": "Cost cuts", "timeline": "FY2026"},
                {"type": "SOFT", "description": "Market shift", "timeline": "2027"},
            ]
        )
        _validate(_valid_payload(candidate))

    def test_catalyst_stack_missing_type_fails(self) -> None:
        candidate = _minimal_candidate(
            catalyst_stack=[{"description": "Missing type", "timeline": "Q1 2026"}]
        )
        with self.assertRaises(SchemaValidationError):
            _validate(_valid_payload(candidate))

    def test_catalyst_stack_empty_fails(self) -> None:
        candidate = _minimal_candidate(catalyst_stack=[])
        with self.assertRaises(SchemaValidationError):
            _validate(_valid_payload(candidate))

    # -- invalidation_triggers --

    def test_invalidation_triggers_valid(self) -> None:
        candidate = _minimal_candidate(
            invalidation_triggers=[
                {"trigger": "CEO leaves", "evidence": "Board instability noted"}
            ]
        )
        _validate(_valid_payload(candidate))

    def test_invalidation_triggers_missing_field_fails(self) -> None:
        candidate = _minimal_candidate(
            invalidation_triggers=[{"trigger": "CEO leaves"}]
        )
        with self.assertRaises(SchemaValidationError):
            _validate(_valid_payload(candidate))

    # -- decision_memo --

    def test_decision_memo_valid(self) -> None:
        candidate = _minimal_candidate(
            decision_memo={
                "better_than_peer": "Higher margins",
                "safer_than_peer": "Lower leverage",
                "what_makes_wrong": "Demand collapses",
            }
        )
        _validate(_valid_payload(candidate))

    def test_decision_memo_missing_field_fails(self) -> None:
        candidate = _minimal_candidate(
            decision_memo={
                "better_than_peer": "Higher margins",
                "safer_than_peer": "Lower leverage",
                # missing what_makes_wrong
            }
        )
        with self.assertRaises(SchemaValidationError):
            _validate(_valid_payload(candidate))

    # -- issues_and_fixes (array) --

    def test_issues_and_fixes_array_valid(self) -> None:
        candidate = _minimal_candidate(
            issues_and_fixes=[
                {
                    "issue": "Plant overcapacity",
                    "fix": "Consolidation",
                    "evidence_status": "ACTION_UNDERWAY",
                },
                {
                    "issue": "Pricing lag",
                    "fix": "Price increases",
                    "evidence_status": "EARLY_RESULTS_VISIBLE",
                },
            ]
        )
        _validate(_valid_payload(candidate))

    def test_issues_and_fixes_invalid_enum_fails(self) -> None:
        candidate = _minimal_candidate(
            issues_and_fixes=[
                {
                    "issue": "Bad status",
                    "fix": "No fix",
                    "evidence_status": "INVALID_STATUS",
                }
            ]
        )
        with self.assertRaises(SchemaValidationError):
            _validate(_valid_payload(candidate))

    def test_issues_and_fixes_old_string_format_fails(self) -> None:
        candidate = _minimal_candidate(
            issues_and_fixes="This is the old string format"
        )
        with self.assertRaises(SchemaValidationError):
            _validate(_valid_payload(candidate))

    # -- setup_pattern --

    def test_setup_pattern_valid_values(self) -> None:
        for pattern in ["SOLVENCY_SCARE", "QUALITY_FRANCHISE", "NARRATIVE_DISCOUNT", "NEW_OPERATOR", "OTHER"]:
            candidate = _minimal_candidate(setup_pattern=pattern)
            _validate(_valid_payload(candidate))

    def test_setup_pattern_invalid_value_fails(self) -> None:
        candidate = _minimal_candidate(setup_pattern="UNKNOWN_PATTERN")
        with self.assertRaises(SchemaValidationError):
            _validate(_valid_payload(candidate))

    # -- stretch_case --

    def test_stretch_case_valid(self) -> None:
        candidate = _minimal_candidate(
            stretch_case={
                "revenue_b": 4.0,
                "fcf_margin_pct": 12.0,
                "multiple": 28.0,
                "shares_m": 120.0,
                "years": 3.0,
            }
        )
        _validate(_valid_payload(candidate))

    def test_stretch_case_missing_required_field_fails(self) -> None:
        candidate = _minimal_candidate(
            stretch_case={
                "revenue_b": 4.0,
                "fcf_margin_pct": 12.0,
                # missing multiple, shares_m, years
            }
        )
        with self.assertRaises(SchemaValidationError):
            _validate(_valid_payload(candidate))


if __name__ == "__main__":
    unittest.main()
