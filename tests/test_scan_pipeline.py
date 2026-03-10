from __future__ import annotations

import tempfile
import json
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.config import AppConfig
from edenfintech_scanner_bootstrap.pipeline import run_scan, run_scan_file


def _no_judge_config() -> AppConfig:
    return AppConfig(
        fmp_api_key=None,
        gemini_api_key=None,
        openai_api_key=None,
        codex_judge_model="gpt-5-codex",
    )


def _enriched_analysis_fields() -> dict:
    """Return the 6 new required analysis fields for schema compliance."""
    return {
        "catalyst_stack": [
            {"type": "HARD", "description": "Pricing reset", "timeline": "Q1 2026"}
        ],
        "invalidation_triggers": [
            {"trigger": "CEO departure", "evidence": "Board instability"}
        ],
        "decision_memo": {
            "better_than_peer": "Stronger margins",
            "safer_than_peer": "Lower leverage",
            "what_makes_wrong": "Demand decline",
        },
        "issues_and_fixes": [
            {"issue": "Plant overcapacity", "fix": "Consolidation", "evidence_status": "ACTION_UNDERWAY"}
        ],
        "setup_pattern": "QUALITY_FRANCHISE",
        "stretch_case": {
            "revenue_b": 4.0,
            "fcf_margin_pct": 12.0,
            "multiple": 28.0,
            "shares_m": 120.0,
            "years": 3.0,
        },
    }


def _base_payload() -> dict:
    return {
        "title": "Pipeline Test Scan",
        "scan_date": "2026-03-08",
        "version": "v1",
        "scan_parameters": {
            "scan_mode": "specific_tickers",
            "focus": "SCRN, EXC, RANK",
            "api": "Fixture Input",
        },
        "portfolio_context": {
            "current_positions": 5,
            "max_positions": 12,
        },
        "methodology_notes": [
            "Pipeline fixture for deterministic stage testing.",
        ],
        "candidates": [],
    }


class ScanPipelineTest(unittest.TestCase):
    def test_schema_validation_rejects_missing_analysis_for_screening_survivor(self) -> None:
        payload = _base_payload()
        payload["candidates"] = [
            {
                "ticker": "MISS",
                "cluster_name": "missing-analysis",
                "industry": "Auto Parts",
                "current_price": 22.0,
                "screening": {
                    "pct_off_ath": 70.0,
                    "industry_understandable": True,
                    "industry_in_secular_decline": False,
                    "double_plus_potential": True,
                    "checks": {
                        "solvency": {"verdict": "PASS", "note": "Adequate liquidity."},
                        "dilution": {"verdict": "PASS", "note": "No dilution concern."},
                        "revenue_growth": {"verdict": "PASS", "note": "Stable."},
                        "roic": {"verdict": "PASS", "note": "Above hurdle."},
                        "valuation": {"verdict": "PASS", "note": "Cheap enough."},
                    },
                },
            }
        ]

        with self.assertRaisesRegex(ValueError, "analysis"):
            run_scan(payload, judge_config=_no_judge_config())

    def test_screening_rejection_requires_only_screening_payload(self) -> None:
        payload = _base_payload()
        payload["candidates"] = [
            {
                "ticker": "SCRN",
                "cluster_name": "screening-cluster",
                "industry": "Auto Parts",
                "current_price": 40.0,
                "screening": {
                    "pct_off_ath": 42.0,
                    "industry_understandable": True,
                    "industry_in_secular_decline": False,
                    "double_plus_potential": True,
                    "checks": {
                        "solvency": {"verdict": "PASS", "note": "Adequate liquidity."},
                        "dilution": {"verdict": "PASS", "note": "No dilution concern."},
                        "revenue_growth": {"verdict": "PASS", "note": "Stable."},
                        "roic": {"verdict": "PASS", "note": "Above hurdle."},
                        "valuation": {"verdict": "PASS", "note": "Cheap enough."},
                    },
                },
            }
        ]

        artifacts = run_scan(payload, judge_config=_no_judge_config())

        self.assertEqual(len(artifacts.report_json["rejected_at_screening"]), 1)
        self.assertEqual(artifacts.report_json["rejected_at_screening"][0]["ticker"], "SCRN")
        self.assertEqual(artifacts.report_json["ranked_candidates"], [])

    def test_exception_candidate_routes_to_pending_human_review(self) -> None:
        payload = _base_payload()
        analysis = {
            "margin_trend_gate": "PASS",
            "final_cluster_status": "CONDITIONAL_WINNER",
            "catalyst_classification": "VALID_CATALYST",
            "dominant_risk_type": "Operational/Financial",
            "base_case": {
                "revenue_b": 6.0,
                "fcf_margin_pct": 7.0,
                "multiple": 15.0,
                "shares_m": 70.0,
                "years": 3.0,
            },
            "worst_case": {
                "revenue_b": 5.4,
                "fcf_margin_pct": 5.0,
                "multiple": 10.0,
                "shares_m": 70.0,
            },
            "probability": {
                "base_probability_pct": 64.0,
                "base_rate": "60% precedent base rate",
            },
            "exception_20_pct_gate": {
                "eligible": True,
                "reason": "Base-case CAGR falls in the exception band with 6yr+ runway and top-tier CEO.",
            },
            **_enriched_analysis_fields(),
        }
        payload["candidates"] = [
            {
                "ticker": "EXC",
                "cluster_name": "exception-cluster",
                "industry": "Credit Services",
                "current_price": 52.0,
                "screening": {
                    "pct_off_ath": 68.0,
                    "industry_understandable": True,
                    "industry_in_secular_decline": False,
                    "double_plus_potential": True,
                    "checks": {
                        "solvency": {"verdict": "PASS", "note": "Adequate balance sheet."},
                        "dilution": {"verdict": "PASS", "note": "Share count stable."},
                        "revenue_growth": {"verdict": "PASS", "note": "Growth reaccelerating."},
                        "roic": {"verdict": "PASS", "note": "Returns normalizing."},
                        "valuation": {"verdict": "PASS", "note": "Preliminary hurdle clears."},
                    },
                },
                "analysis": analysis,
                "epistemic_review": {
                    "q1_operational": {"answer": "Yes", "justification": "Modelable execution risk.", "evidence": "Operating plan."},
                    "q2_regulatory": {"answer": "Yes", "justification": "Stable regulatory setup.", "evidence": "Routine oversight."},
                    "q3_precedent": {"answer": "Yes", "justification": "Comparable recoveries exist.", "evidence": "Historical peers."},
                    "q4_nonbinary": {"answer": "Yes", "justification": "Several recovery paths exist.", "evidence": "Margin levers."},
                    "q5_macro": {"answer": "Yes", "justification": "Macro is secondary.", "evidence": "Domestic exposure."},
                },
            }
        ]

        artifacts = run_scan(payload, judge_config=_no_judge_config())

        self.assertEqual(artifacts.report_json["ranked_candidates"], [])
        self.assertEqual(len(artifacts.report_json["pending_human_review"]), 1)
        self.assertEqual(artifacts.report_json["pending_human_review"][0]["ticker"], "EXC")

    def test_ranked_candidate_clears_full_pipeline(self) -> None:
        payload = _base_payload()
        payload["portfolio_context"]["current_holdings"] = [
            {
                "ticker": "RANK",
                "current_weight_pct": 4.5,
                "existing_position_action": "HOLD",
                "note": "Existing position in monitored sleeve.",
            }
        ]
        payload["candidates"] = [
            {
                "ticker": "RANK",
                "cluster_name": "ranked-cluster",
                "industry": "Industrial Components",
                "current_price": 25.0,
                "screening": {
                    "pct_off_ath": 75.0,
                    "industry_understandable": True,
                    "industry_in_secular_decline": False,
                    "double_plus_potential": True,
                    "checks": {
                        "solvency": {"verdict": "PASS", "note": "Liquidity is strong."},
                        "dilution": {"verdict": "PASS", "note": "Per-share growth positive."},
                        "revenue_growth": {"verdict": "PASS", "note": "Growth base stable."},
                        "roic": {"verdict": "PASS", "note": "ROIC above threshold."},
                        "valuation": {"verdict": "PASS", "note": "Valuation clears hurdle."},
                    },
                },
                "analysis": {
                    "margin_trend_gate": "PASS",
                    "final_cluster_status": "CLEAR_WINNER",
                    "catalyst_classification": "VALID_CATALYST",
                    "moat_assessment": "Switching costs and distribution scale remain intact.",
                    "thesis_summary": "Recovery candidate with favorable asymmetry and clear catalysts.",
                    "catalysts": ["Pricing reset", "Plant consolidation"],
                    "key_risks": ["Execution slippage"],
                    "dominant_risk_type": "Operational/Financial",
                    "base_case": {
                        "revenue_b": 3.6,
                        "fcf_margin_pct": 10.0,
                        "multiple": 20.0,
                        "shares_m": 120.0,
                        "years": 3.0,
                    },
                    "worst_case": {
                        "revenue_b": 2.8,
                        "fcf_margin_pct": 8.0,
                        "multiple": 12.0,
                        "shares_m": 120.0,
                    },
                    "probability": {
                        "base_probability_pct": 72.0,
                        "base_rate": "70% precedent base rate",
                        "likert_adjustments": "Management +10, balance sheet 0, market 0",
                    },
                    "exception_20_pct_gate": {
                        "eligible": False,
                    },
                    **_enriched_analysis_fields(),
                },
                "epistemic_review": {
                    "q1_operational": {"answer": "Yes", "justification": "Risks are operational.", "evidence": "Known plant fixes."},
                    "q2_regulatory": {"answer": "Yes", "justification": "Low regulatory discretion.", "evidence": "Normal approvals."},
                    "q3_precedent": {"answer": "Yes", "justification": "There are clear precedents.", "evidence": "Peer turnaround set."},
                    "q4_nonbinary": {"answer": "Yes", "justification": "Outcome range is not binary.", "evidence": "Gradual margin path."},
                    "q5_macro": {"answer": "Yes", "justification": "Macro exposure is limited.", "evidence": "Mostly contractual demand."},
                },
            }
        ]

        artifacts = run_scan(payload, judge_config=_no_judge_config())

        self.assertEqual(len(artifacts.report_json["ranked_candidates"]), 1)
        ranked = artifacts.report_json["ranked_candidates"][0]
        self.assertEqual(ranked["ticker"], "RANK")
        self.assertGreaterEqual(ranked["epistemic_confidence"]["effective_probability"], 60.0)
        self.assertEqual(artifacts.judge["verdict"], "APPROVE")
        self.assertEqual(len(artifacts.report_json["current_holding_overlays"]), 1)
        self.assertEqual(artifacts.report_json["current_holding_overlays"][0]["ticker"], "RANK")
        self.assertEqual(artifacts.report_json["current_holding_overlays"][0]["status_in_scan"], "RANKED")

    def test_current_holding_overlays_cover_pending_and_out_of_scope(self) -> None:
        payload = _base_payload()
        payload["portfolio_context"]["current_holdings"] = [
            {
                "ticker": "EXC",
                "current_weight_pct": 3.0,
                "existing_position_action": "HOLD_AND_MONITOR",
                "note": "Exception candidate currently held.",
            },
            {
                "ticker": "OUT",
                "current_weight_pct": 2.0,
                "existing_position_action": "HOLD",
                "note": "Not part of this scan.",
            },
        ]
        payload["candidates"] = [
            {
                "ticker": "EXC",
                "cluster_name": "exception-cluster",
                "industry": "Credit Services",
                "current_price": 52.0,
                "screening": {
                    "pct_off_ath": 68.0,
                    "industry_understandable": True,
                    "industry_in_secular_decline": False,
                    "double_plus_potential": True,
                    "checks": {
                        "solvency": {"verdict": "PASS", "note": "Adequate balance sheet."},
                        "dilution": {"verdict": "PASS", "note": "Share count stable."},
                        "revenue_growth": {"verdict": "PASS", "note": "Growth reaccelerating."},
                        "roic": {"verdict": "PASS", "note": "Returns normalizing."},
                        "valuation": {"verdict": "PASS", "note": "Preliminary hurdle clears."},
                    },
                },
                "analysis": {
                    "margin_trend_gate": "PASS",
                    "final_cluster_status": "CONDITIONAL_WINNER",
                    "catalyst_classification": "VALID_CATALYST",
                    "dominant_risk_type": "Operational/Financial",
                    "base_case": {
                        "revenue_b": 6.0,
                        "fcf_margin_pct": 7.0,
                        "multiple": 15.0,
                        "shares_m": 70.0,
                        "years": 3.0,
                    },
                    "worst_case": {
                        "revenue_b": 5.4,
                        "fcf_margin_pct": 5.0,
                        "multiple": 10.0,
                        "shares_m": 70.0,
                    },
                    "probability": {"base_probability_pct": 64.0},
                    "exception_20_pct_gate": {
                        "eligible": True,
                        "reason": "Human approval required.",
                    },
                    **_enriched_analysis_fields(),
                },
                "epistemic_review": {
                    "q1_operational": {"answer": "Yes", "justification": "Modelable execution risk.", "evidence": "Operating plan."},
                    "q2_regulatory": {"answer": "Yes", "justification": "Stable regulatory setup.", "evidence": "Routine oversight."},
                    "q3_precedent": {"answer": "Yes", "justification": "Comparable recoveries exist.", "evidence": "Historical peers."},
                    "q4_nonbinary": {"answer": "Yes", "justification": "Several recovery paths exist.", "evidence": "Margin levers."},
                    "q5_macro": {"answer": "Yes", "justification": "Macro is secondary.", "evidence": "Domestic exposure."},
                },
            }
        ]

        artifacts = run_scan(payload, judge_config=_no_judge_config())

        overlays = {item["ticker"]: item for item in artifacts.report_json["current_holding_overlays"]}
        self.assertEqual(overlays["EXC"]["status_in_scan"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(overlays["OUT"]["status_in_scan"], "NOT_IN_SCAN_SCOPE")

    def test_run_scan_file_writes_execution_log_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            report_path = Path(tmpdir) / "report.json"
            markdown_path = Path(tmpdir) / "report.md"
            execution_log_path = Path(tmpdir) / "execution-log.md"
            scan_payload = {
                "title": "Execution Log Test",
                "scan_date": "2026-03-08",
                "version": "v1",
                "scan_parameters": {"scan_mode": "specific_tickers", "focus": "RANK", "api": "Fixture Input"},
                "portfolio_context": {"current_positions": 1, "max_positions": 12},
                "methodology_notes": ["Execution log file test."],
                "candidates": [
                    {
                        "ticker": "RANK",
                        "cluster_name": "ranked-cluster",
                        "industry": "Industrial Components",
                        "current_price": 25.0,
                        "screening": {
                            "pct_off_ath": 75.0,
                            "industry_understandable": True,
                            "industry_in_secular_decline": False,
                            "double_plus_potential": True,
                            "checks": {
                                "solvency": {"verdict": "PASS", "note": "Liquidity is strong."},
                                "dilution": {"verdict": "PASS", "note": "Per-share growth positive."},
                                "revenue_growth": {"verdict": "PASS", "note": "Growth base stable."},
                                "roic": {"verdict": "PASS", "note": "ROIC above threshold."},
                                "valuation": {"verdict": "PASS", "note": "Valuation clears hurdle."},
                            },
                        },
                        "analysis": {
                            "margin_trend_gate": "PASS",
                            "final_cluster_status": "CLEAR_WINNER",
                            "catalyst_classification": "VALID_CATALYST",
                            "moat_assessment": "Switching costs and distribution scale remain intact.",
                            "thesis_summary": "Recovery candidate with favorable asymmetry and clear catalysts.",
                            "catalysts": ["Pricing reset", "Plant consolidation"],
                            "key_risks": ["Execution slippage"],
                            "dominant_risk_type": "Operational/Financial",
                            "base_case": {"revenue_b": 3.6, "fcf_margin_pct": 10.0, "multiple": 20.0, "shares_m": 120.0, "years": 3.0},
                            "worst_case": {"revenue_b": 2.8, "fcf_margin_pct": 8.0, "multiple": 12.0, "shares_m": 120.0},
                            "probability": {"base_probability_pct": 72.0, "base_rate": "70% precedent base rate"},
                            "exception_20_pct_gate": {"eligible": False},
                            **_enriched_analysis_fields(),
                        },
                        "epistemic_review": {
                            "q1_operational": {"answer": "Yes", "justification": "Risks are operational.", "evidence": "Known plant fixes."},
                            "q2_regulatory": {"answer": "Yes", "justification": "Low regulatory discretion.", "evidence": "Normal approvals."},
                            "q3_precedent": {"answer": "Yes", "justification": "There are clear precedents.", "evidence": "Peer turnaround set."},
                            "q4_nonbinary": {"answer": "Yes", "justification": "Outcome range is not binary.", "evidence": "Gradual margin path."},
                            "q5_macro": {"answer": "Yes", "justification": "Macro exposure is limited.", "evidence": "Mostly contractual demand."},
                        },
                    }
                ],
            }
            input_path.write_text(json.dumps(scan_payload, indent=2))

            artifacts = run_scan_file(
                input_path,
                json_out=report_path,
                markdown_out=markdown_path,
                execution_log_out=execution_log_path,
                judge_config=_no_judge_config(),
            )

            self.assertTrue(report_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertTrue(execution_log_path.exists())
            self.assertNotIn("execution_log", artifacts.report_json)
            self.assertNotIn("execution_log", json.loads(report_path.read_text()))
            self.assertIn("Stage Events", execution_log_path.read_text())


class TestPipelineGates(unittest.TestCase):
    """Tests for catalyst_stack and issues_and_fixes pipeline validation gates."""

    def _gate_candidate(self, **analysis_overrides) -> dict:
        """Return a candidate that passes screening and all analysis gates by default."""
        analysis = {
            "margin_trend_gate": "PASS",
            "final_cluster_status": "CLEAR_WINNER",
            "catalyst_classification": "VALID_CATALYST",
            "dominant_risk_type": "Operational/Financial",
            "base_case": {
                "revenue_b": 3.6,
                "fcf_margin_pct": 10.0,
                "multiple": 20.0,
                "shares_m": 120.0,
                "years": 3.0,
            },
            "worst_case": {
                "revenue_b": 2.8,
                "fcf_margin_pct": 8.0,
                "multiple": 12.0,
                "shares_m": 120.0,
            },
            "probability": {"base_probability_pct": 72.0},
            "exception_20_pct_gate": {"eligible": False},
            **_enriched_analysis_fields(),
        }
        analysis.update(analysis_overrides)
        return {
            "ticker": "GATE",
            "cluster_name": "gate-cluster",
            "industry": "Industrial Components",
            "current_price": 25.0,
            "screening": {
                "pct_off_ath": 75.0,
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
            "analysis": analysis,
            "epistemic_review": {
                "q1_operational": {"answer": "Yes", "justification": "j", "evidence": "e"},
                "q2_regulatory": {"answer": "Yes", "justification": "j", "evidence": "e"},
                "q3_precedent": {"answer": "Yes", "justification": "j", "evidence": "e"},
                "q4_nonbinary": {"answer": "Yes", "justification": "j", "evidence": "e"},
                "q5_macro": {"answer": "Yes", "justification": "j", "evidence": "e"},
            },
        }

    def test_rejects_no_hard_medium_catalysts(self) -> None:
        payload = _base_payload()
        payload["candidates"] = [
            self._gate_candidate(
                catalyst_stack=[
                    {"type": "SOFT", "description": "Market sentiment", "timeline": "2026"},
                    {"type": "SOFT", "description": "Industry tailwind", "timeline": "2027"},
                ]
            )
        ]
        with self.assertRaisesRegex(ValueError, "catalyst_stack"):
            run_scan(payload, judge_config=_no_judge_config())

    def test_rejects_all_announced_only(self) -> None:
        payload = _base_payload()
        payload["candidates"] = [
            self._gate_candidate(
                issues_and_fixes=[
                    {"issue": "Cost structure", "fix": "Plan announced", "evidence_status": "ANNOUNCED_ONLY"},
                    {"issue": "Pricing lag", "fix": "Review planned", "evidence_status": "ANNOUNCED_ONLY"},
                ]
            )
        ]
        with self.assertRaisesRegex(ValueError, "issues_and_fixes"):
            run_scan(payload, judge_config=_no_judge_config())

    def test_passes_with_hard_catalyst(self) -> None:
        payload = _base_payload()
        payload["candidates"] = [
            self._gate_candidate(
                catalyst_stack=[
                    {"type": "HARD", "description": "Pricing reset", "timeline": "Q1 2026"}
                ]
            )
        ]
        # Should not raise
        artifacts = run_scan(payload, judge_config=_no_judge_config())
        self.assertIsNotNone(artifacts)

    def test_passes_with_mixed_evidence(self) -> None:
        payload = _base_payload()
        payload["candidates"] = [
            self._gate_candidate(
                issues_and_fixes=[
                    {"issue": "Cost structure", "fix": "Plan announced", "evidence_status": "ANNOUNCED_ONLY"},
                    {"issue": "Pricing lag", "fix": "Increases visible", "evidence_status": "ACTION_UNDERWAY"},
                ]
            )
        ]
        # Should not raise
        artifacts = run_scan(payload, judge_config=_no_judge_config())
        self.assertIsNotNone(artifacts)


if __name__ == "__main__":
    unittest.main()
