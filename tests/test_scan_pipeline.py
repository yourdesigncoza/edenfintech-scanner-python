from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.pipeline import run_scan, run_scan_file


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
            run_scan(payload)

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

        artifacts = run_scan(payload)

        self.assertEqual(len(artifacts.report_json["rejected_at_screening"]), 1)
        self.assertEqual(artifacts.report_json["rejected_at_screening"][0]["ticker"], "SCRN")
        self.assertEqual(artifacts.report_json["ranked_candidates"], [])

    def test_exception_candidate_routes_to_pending_human_review(self) -> None:
        payload = _base_payload()
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
                    "probability": {
                        "base_probability_pct": 64.0,
                        "base_rate": "60% precedent base rate",
                    },
                    "exception_20_pct_gate": {
                        "eligible": True,
                        "reason": "Base-case CAGR falls in the exception band with 6yr+ runway and top-tier CEO.",
                    },
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

        artifacts = run_scan(payload)

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
                    "issues_and_fixes": "Turnaround actions are already visible in margins.",
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

        artifacts = run_scan(payload)

        self.assertEqual(len(artifacts.report_json["ranked_candidates"]), 1)
        ranked = artifacts.report_json["ranked_candidates"][0]
        self.assertEqual(ranked["ticker"], "RANK")
        self.assertGreaterEqual(ranked["epistemic_confidence"]["effective_probability"], 60.0)
        self.assertEqual(artifacts.judge["verdict"], "APPROVE")
        self.assertEqual(len(artifacts.report_json["current_holding_overlays"]), 1)
        self.assertEqual(artifacts.report_json["current_holding_overlays"][0]["ticker"], "RANK")
        self.assertEqual(artifacts.report_json["current_holding_overlays"][0]["status_in_scan"], "RANKED")

    def test_run_scan_file_writes_execution_log_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            report_path = Path(tmpdir) / "report.json"
            markdown_path = Path(tmpdir) / "report.md"
            execution_log_path = Path(tmpdir) / "execution-log.md"
            input_path.write_text(
                """{
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
        "industry_understandable": true,
        "industry_in_secular_decline": false,
        "double_plus_potential": true,
        "checks": {
          "solvency": {"verdict": "PASS", "note": "Liquidity is strong."},
          "dilution": {"verdict": "PASS", "note": "Per-share growth positive."},
          "revenue_growth": {"verdict": "PASS", "note": "Growth base stable."},
          "roic": {"verdict": "PASS", "note": "ROIC above threshold."},
          "valuation": {"verdict": "PASS", "note": "Valuation clears hurdle."}
        }
      },
      "analysis": {
        "margin_trend_gate": "PASS",
        "final_cluster_status": "CLEAR_WINNER",
        "catalyst_classification": "VALID_CATALYST",
        "issues_and_fixes": "Turnaround actions are already visible in margins.",
        "moat_assessment": "Switching costs and distribution scale remain intact.",
        "thesis_summary": "Recovery candidate with favorable asymmetry and clear catalysts.",
        "catalysts": ["Pricing reset", "Plant consolidation"],
        "key_risks": ["Execution slippage"],
        "dominant_risk_type": "Operational/Financial",
        "base_case": {"revenue_b": 3.6, "fcf_margin_pct": 10.0, "multiple": 20.0, "shares_m": 120.0, "years": 3.0},
        "worst_case": {"revenue_b": 2.8, "fcf_margin_pct": 8.0, "multiple": 12.0, "shares_m": 120.0},
        "probability": {"base_probability_pct": 72.0, "base_rate": "70% precedent base rate"},
        "exception_20_pct_gate": {"eligible": false}
      },
      "epistemic_review": {
        "q1_operational": {"answer": "Yes", "justification": "Risks are operational.", "evidence": "Known plant fixes."},
        "q2_regulatory": {"answer": "Yes", "justification": "Low regulatory discretion.", "evidence": "Normal approvals."},
        "q3_precedent": {"answer": "Yes", "justification": "There are clear precedents.", "evidence": "Peer turnaround set."},
        "q4_nonbinary": {"answer": "Yes", "justification": "Outcome range is not binary.", "evidence": "Gradual margin path."},
        "q5_macro": {"answer": "Yes", "justification": "Macro exposure is limited.", "evidence": "Mostly contractual demand."}
      }
    }
  ]
}"""
            )

            artifacts = run_scan_file(
                input_path,
                json_out=report_path,
                markdown_out=markdown_path,
                execution_log_out=execution_log_path,
            )

            self.assertTrue(report_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertTrue(execution_log_path.exists())
            self.assertIn("execution_log", artifacts.report_json)
            self.assertIn("Stage Events", execution_log_path.read_text())


if __name__ == "__main__":
    unittest.main()
