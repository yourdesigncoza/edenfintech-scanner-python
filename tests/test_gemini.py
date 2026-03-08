from __future__ import annotations

import json
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.config import AppConfig
from edenfintech_scanner_bootstrap.gemini import (
    DEFAULT_GEMINI_MODEL,
    build_gemini_bundle_with_config,
    merge_fmp_and_gemini_bundles,
)


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "gemini"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


class GeminiTest(unittest.TestCase):
    def test_builds_retrieval_only_bundle(self) -> None:
        seen_requests: list[dict] = []

        def transport(url: str, headers: dict[str, str], payload: dict) -> dict:
            seen_requests.append({"url": url, "headers": headers, "payload": payload})
            return _load_fixture("generate_content_rest_raw1.json")

        bundle = build_gemini_bundle_with_config(
            ["RAW1"],
            config=AppConfig(
                fmp_api_key=None,
                gemini_api_key="gemini-test-key",
                openai_api_key=None,
                codex_judge_model="gpt-5-codex",
            ),
            transport=transport,
            focus="fintech vertical software",
            research_question="Collect source-backed catalysts and risks.",
        )

        self.assertEqual(bundle["scan_parameters"]["api"], "Gemini")
        self.assertEqual(len(bundle["raw_candidates"]), 1)
        self.assertEqual(bundle["raw_candidates"][0]["ticker"], "RAW1")
        self.assertEqual(
            bundle["raw_candidates"][0]["gemini_context"]["prompt_context"]["model"],
            DEFAULT_GEMINI_MODEL,
        )
        self.assertIn("googleSearch", seen_requests[0]["payload"]["tools"][0])
        self.assertEqual(
            seen_requests[0]["payload"]["generationConfig"]["responseMimeType"],
            "application/json",
        )

    def test_requires_gemini_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required configuration: gemini_api_key"):
            build_gemini_bundle_with_config(
                ["RAW1"],
                config=AppConfig(
                    fmp_api_key=None,
                    gemini_api_key=None,
                    openai_api_key=None,
                    codex_judge_model="gpt-5-codex",
                ),
            )

    def test_rejects_methodology_keys_in_model_output(self) -> None:
        def transport(url: str, headers: dict[str, str], payload: dict) -> dict:
            return {
                "candidates": [
                {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "research_notes": [],
                                            "catalyst_evidence": [],
                                            "risk_evidence": [],
                                            "management_observations": [],
                                            "moat_observations": [],
                                            "precedent_observations": [],
                                            "epistemic_anchors": [],
                                            "screening_inputs": {"solvency": "pass"},
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
                }

        with self.assertRaisesRegex(ValueError, "forbidden methodology keys: screening_inputs"):
            build_gemini_bundle_with_config(
                ["RAW1"],
                config=AppConfig(
                    fmp_api_key=None,
                    gemini_api_key="gemini-test-key",
                    openai_api_key=None,
                    codex_judge_model="gpt-5-codex",
                ),
                transport=transport,
            )

    def test_builds_bundle_from_sdk_style_text_field(self) -> None:
        def transport(url: str, headers: dict[str, str], payload: dict) -> dict:
            return _load_fixture("generate_content_sdk_raw1.json")

        bundle = build_gemini_bundle_with_config(
            ["RAW1"],
            config=AppConfig(
                fmp_api_key=None,
                gemini_api_key="gemini-test-key",
                openai_api_key=None,
                codex_judge_model="gpt-5-codex",
            ),
            transport=transport,
        )

        self.assertEqual(bundle["raw_candidates"][0]["ticker"], "RAW1")

    def test_merge_combines_overlapping_fmp_and_gemini_candidates(self) -> None:
        fmp_bundle = {
            "title": "EdenFinTech FMP Raw Bundle - RAW1",
            "scan_date": "2026-03-08",
            "version": "v1",
            "scan_parameters": {
                "scan_mode": "specific_tickers",
                "focus": "RAW1",
                "api": "Financial Modeling Prep",
            },
            "portfolio_context": {
                "current_positions": 2,
                "max_positions": 12,
            },
            "methodology_notes": [
                "This bundle was fetched from FMP and contains deterministic market and financial inputs only."
            ],
            "raw_candidates": [
                {
                    "ticker": "RAW1",
                    "cluster_name": "raw1-cluster",
                    "industry": "Industrial Components",
                    "current_price": 24.0,
                },
            ],
        }
        gemini_bundle = {
            "title": "EdenFinTech Gemini Raw Bundle - RAW1",
            "scan_date": "2026-03-08",
            "version": "v1",
            "scan_parameters": {
                "scan_mode": "specific_tickers",
                "focus": "RAW1",
                "api": "Gemini",
            },
            "methodology_notes": [
                "This bundle was fetched from Gemini and contains sourced qualitative evidence only."
            ],
            "raw_candidates": [
                {
                    "ticker": "RAW1",
                    "gemini_context": {
                        "prompt_context": {
                            "model": DEFAULT_GEMINI_MODEL,
                            "research_question": "Collect source-backed catalysts and risks.",
                            "search_scope": "RAW1",
                        },
                        "research_notes": [],
                        "catalyst_evidence": [],
                        "risk_evidence": [],
                        "management_observations": [],
                        "moat_observations": [],
                        "precedent_observations": [],
                        "epistemic_anchors": [],
                    },
                },
            ],
        }

        merged = merge_fmp_and_gemini_bundles(fmp_bundle, gemini_bundle)

        self.assertEqual(merged["scan_parameters"]["api"], "Financial Modeling Prep + Gemini")
        self.assertEqual(len(merged["raw_candidates"]), 1)
        raw1 = next(candidate for candidate in merged["raw_candidates"] if candidate["ticker"] == "RAW1")
        self.assertEqual(raw1["industry"], "Industrial Components")
        self.assertIn("gemini_context", raw1)

    def test_merge_rejects_gemini_tickers_missing_from_fmp_bundle(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing from the FMP bundle: RAW3"):
            merge_fmp_and_gemini_bundles(
                {
                    "raw_candidates": [
                        {
                            "ticker": "RAW1",
                            "cluster_name": "raw1-cluster",
                            "industry": "Industrial Components",
                            "current_price": 24.0,
                        }
                    ]
                },
                {
                    "title": "Gemini",
                    "scan_date": "2026-03-08",
                    "version": "v1",
                    "scan_parameters": {
                        "scan_mode": "specific_tickers",
                        "focus": "RAW1, RAW3",
                        "api": "Gemini",
                    },
                    "methodology_notes": ["retrieval only"],
                    "raw_candidates": [
                        {
                            "ticker": "RAW1",
                            "gemini_context": {
                                "prompt_context": {
                                    "model": DEFAULT_GEMINI_MODEL,
                                    "research_question": "Question",
                                    "search_scope": "RAW1, RAW3",
                                },
                                "research_notes": [],
                                "catalyst_evidence": [],
                                "risk_evidence": [],
                                "management_observations": [],
                                "moat_observations": [],
                                "precedent_observations": [],
                                "epistemic_anchors": [],
                            },
                        },
                        {
                            "ticker": "RAW3",
                            "gemini_context": {
                                "prompt_context": {
                                    "model": DEFAULT_GEMINI_MODEL,
                                    "research_question": "Question",
                                    "search_scope": "RAW1, RAW3",
                                },
                                "research_notes": [],
                                "catalyst_evidence": [],
                                "risk_evidence": [],
                                "management_observations": [],
                                "moat_observations": [],
                                "precedent_observations": [],
                                "epistemic_anchors": [],
                            },
                        },
                    ],
                },
            )


if __name__ == "__main__":
    unittest.main()
