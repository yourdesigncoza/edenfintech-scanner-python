from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edenfintech_scanner_bootstrap.config import AppConfig, discover_dotenv_path, load_config
from edenfintech_scanner_bootstrap.importers import build_scan_input, build_scan_input_file
from edenfintech_scanner_bootstrap.pipeline import run_scan


FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "raw"


class ConfigTest(unittest.TestCase):
    def test_load_config_reads_dotenv_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text(
                "FMP_API_KEY=fmp-test\n"
                "GEMINI_API_KEY=gemini-test\n"
                "OPENAI_API_KEY=openai-test\n"
                "CODEX_JUDGE_MODEL=gpt-5-codex\n"
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(dotenv_path)

        self.assertEqual(config.fmp_api_key, "fmp-test")
        self.assertEqual(config.gemini_api_key, "gemini-test")
        self.assertEqual(config.openai_api_key, "openai-test")
        self.assertEqual(config.codex_judge_model, "gpt-5-codex")

    def test_discover_dotenv_path_finds_repo_root_from_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_repo = Path(tmpdir) / "fake-repo"
            (fake_repo / "assets" / "methodology").mkdir(parents=True)
            (fake_repo / "assets" / "methodology" / "scan-report.schema.json").write_text("{}")
            (fake_repo / "pyproject.toml").write_text("[project]\nname='fake'\n")
            dotenv_path = fake_repo / ".env"
            dotenv_path.write_text("OPENAI_API_KEY=repo-root-key\n")

            discovered = discover_dotenv_path(fake_repo / "nested" / "deeper")
            self.assertEqual(discovered, dotenv_path)

            with patch.dict(os.environ, {}, clear=True):
                config = load_config(discovered)

        self.assertEqual(config.openai_api_key, "repo-root-key")


class ImporterE2ETest(unittest.TestCase):
    def test_raw_bundle_imports_and_runs_scan(self) -> None:
        raw_input_path = FIXTURES_ROOT / "ranked_candidate_bundle.json"
        scan_input = build_scan_input_file(raw_input_path)

        self.assertEqual(scan_input["candidates"][0]["ticker"], "RAW1")
        self.assertEqual(scan_input["candidates"][0]["analysis"]["base_case"]["multiple"], 20.0)

        artifacts = run_scan(
            scan_input,
            judge_config=AppConfig(
                fmp_api_key=None,
                gemini_api_key=None,
                openai_api_key=None,
                codex_judge_model="gpt-5-codex",
            ),
        )

        self.assertEqual(len(artifacts.report_json["ranked_candidates"]), 1)
        ranked = artifacts.report_json["ranked_candidates"][0]
        self.assertEqual(ranked["ticker"], "RAW1")
        self.assertEqual(artifacts.judge["verdict"], "APPROVE")

    def test_build_scan_input_validates_imported_payload(self) -> None:
        raw_payload = {
            "scan_parameters": {
                "scan_mode": "specific_tickers",
                "focus": "BROKEN",
            },
            "raw_candidates": [
                {
                    "ticker": "BROKEN",
                    "cluster_name": "broken-cluster",
                    "industry": "Industrial Components",
                    "current_price": 20.0,
                    "market_snapshot": {"pct_off_ath": 75.0},
                    "screening_inputs": {
                        "industry_understandable": True,
                        "industry_in_secular_decline": False,
                        "double_plus_potential": True,
                        "solvency": {"verdict": "PASS", "evidence": "ok"},
                        "dilution": {"verdict": "PASS", "evidence": "ok"},
                        "revenue_growth": {"verdict": "PASS", "evidence": "ok"},
                        "roic": {"verdict": "PASS", "evidence": "ok"},
                        "valuation": {"verdict": "PASS", "evidence": "ok"}
                    }
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "analysis"):
            build_scan_input(raw_payload)

    def test_gemini_context_enriches_analysis_and_reaches_report(self) -> None:
        raw_payload = {
            "title": "Gemini Enriched Raw Scan",
            "scan_date": "2026-03-08",
            "version": "v1",
            "scan_parameters": {
                "scan_mode": "specific_tickers",
                "focus": "RAW1",
                "api": "FMP + Gemini imported bundle",
            },
            "raw_candidates": [
                {
                    "ticker": "RAW1",
                    "cluster_name": "raw1-cluster",
                    "industry": "Industrial Components",
                    "current_price": 20.0,
                    "market_snapshot": {"pct_off_ath": 75.0},
                    "screening_inputs": {
                        "industry_understandable": True,
                        "industry_in_secular_decline": False,
                        "double_plus_potential": True,
                        "solvency": {"verdict": "PASS", "evidence": "ok"},
                        "dilution": {"verdict": "PASS", "evidence": "ok"},
                        "revenue_growth": {"verdict": "PASS", "evidence": "ok"},
                        "roic": {"verdict": "PASS", "evidence": "ok"},
                        "valuation": {"verdict": "PASS", "evidence": "ok"},
                    },
                    "analysis_inputs": {
                        "margin_trend_gate": "PASS",
                        "final_cluster_status": "CLEAR_WINNER",
                        "catalyst_classification": "VALID_CATALYST",
                        "dominant_risk_type": "Operational/Financial",
                        "moat_assessment": "Existing moat note.",
                        "base_case_assumptions": {
                            "revenue_b": 3.4,
                            "fcf_margin_pct": 10.0,
                            "multiple": 20.0,
                            "shares_m": 110.0,
                            "years": 3.0,
                        },
                        "worst_case_assumptions": {
                            "revenue_b": 2.9,
                            "fcf_margin_pct": 7.0,
                            "multiple": 12.0,
                            "shares_m": 110.0,
                        },
                        "probability_inputs": {
                            "base_probability_pct": 72.0,
                        },
                    },
                    "epistemic_inputs": {
                        "q1_operational": {"answer": "Yes", "justification": "ok", "evidence": "ok"},
                        "q2_regulatory": {"answer": "Yes", "justification": "ok", "evidence": "ok"},
                        "q3_precedent": {"answer": "Yes", "justification": "ok", "evidence": "ok"},
                        "q4_nonbinary": {"answer": "Yes", "justification": "ok", "evidence": "ok"},
                        "q5_macro": {"answer": "Yes", "justification": "ok", "evidence": "ok"},
                    },
                    "gemini_context": {
                        "prompt_context": {
                            "model": "gemini-3-pro-preview",
                            "research_question": "Collect source-backed catalysts and risks.",
                            "search_scope": "RAW1",
                        },
                        "research_notes": [
                            {
                                "claim": "Demand is improving in core end markets.",
                                "source_title": "Investor deck",
                                "source_url": "https://example.com/deck",
                            }
                        ],
                        "catalyst_evidence": [
                            {
                                "claim": "A pricing reset is underway.",
                                "source_title": "Earnings call",
                                "source_url": "https://example.com/call",
                            }
                        ],
                        "risk_evidence": [
                            {
                                "claim": "Plant execution remains a near-term risk.",
                                "source_title": "10-K",
                                "source_url": "https://example.com/10k",
                            }
                        ],
                        "management_observations": [
                            {
                                "claim": "Management tied compensation to margin targets.",
                                "source_title": "Proxy",
                                "source_url": "https://example.com/proxy",
                            }
                        ],
                        "moat_observations": [
                            {
                                "claim": "Qualification cycles create sticky customer relationships.",
                                "source_title": "Industry note",
                                "source_url": "https://example.com/note",
                            }
                        ],
                        "precedent_observations": [
                            {
                                "claim": "Peer turnarounds have rerated after similar plant fixes.",
                                "source_title": "Sector precedent",
                                "source_url": "https://example.com/precedent",
                            }
                        ],
                        "epistemic_anchors": [
                            {
                                "claim": "Quarterly gross margin is the key live checkpoint.",
                                "source_title": "Model note",
                                "source_url": "https://example.com/model",
                            }
                        ],
                    },
                }
            ],
        }

        scan_input = build_scan_input(raw_payload)
        analysis = scan_input["candidates"][0]["analysis"]
        self.assertIn("A pricing reset is underway.", analysis["catalysts"][0])
        self.assertIn("Plant execution remains a near-term risk.", analysis["key_risks"][0])
        self.assertIn("Qualification cycles create sticky customer relationships.", analysis["moat_assessment"])
        self.assertIn("source_research", analysis)

        artifacts = run_scan(
            scan_input,
            judge_config=AppConfig(
                fmp_api_key=None,
                gemini_api_key=None,
                openai_api_key=None,
                codex_judge_model="gpt-5-codex",
            ),
        )

        ranked = artifacts.report_json["ranked_candidates"][0]
        self.assertIn("source_research", ranked)
        self.assertEqual(ranked["source_research"]["prompt_context"]["model"], "gemini-3-pro-preview")


if __name__ == "__main__":
    unittest.main()
