from __future__ import annotations

import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.config import AppConfig
from edenfintech_scanner_bootstrap.importers import build_scan_input_file
from edenfintech_scanner_bootstrap.judge import codex_judge, local_judge, validate_judge_result
from edenfintech_scanner_bootstrap.pipeline import run_scan


FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "raw"


class JudgeTest(unittest.TestCase):
    def test_validate_judge_result_rejects_contradictory_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "APPROVE verdict must target approve"):
            validate_judge_result(
                {
                    "verdict": "APPROVE",
                    "target_stage": "report_assembly",
                    "findings": [],
                    "reroute_reason": "",
                }
            )

        with self.assertRaisesRegex(ValueError, "REVISE verdict must target a prior stage"):
            validate_judge_result(
                {
                    "verdict": "REVISE",
                    "target_stage": "approve",
                    "findings": ["Need richer evidence."],
                    "reroute_reason": "judge_payload_invalid",
                }
            )

    def test_local_judge_returns_contract_shape_only(self) -> None:
        result = local_judge(
            {
                "ranked_candidates": [],
                "pending_human_review": [],
                "rejected_at_analysis_detail_packets": [],
                "current_holding_overlays": [],
            },
            {"entries": [], "candidate_count": 0, "survivor_count": 0},
        )

        self.assertEqual(set(result), {"verdict", "target_stage", "findings", "reroute_reason"})
        self.assertEqual(result["verdict"], "APPROVE")

    def test_codex_judge_falls_back_to_local_when_transport_is_invalid(self) -> None:
        report = {
            "ranked_candidates": [],
            "pending_human_review": [],
            "rejected_at_analysis_detail_packets": [],
            "current_holding_overlays": [],
        }
        execution_log = {"entries": [], "candidate_count": 0, "survivor_count": 0}
        config = AppConfig(
            fmp_api_key=None,
            gemini_api_key=None,
            openai_api_key="test-key",
            codex_judge_model="gpt-5-codex",
        )

        result = codex_judge(
            report,
            execution_log,
            config=config,
            transport=lambda payload, app_config: {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"verdict\": \"APPROVE\"}"}]}]},
        )

        self.assertEqual(result["verdict"], "REVISE")
        self.assertEqual(result["target_stage"], "report_assembly")
        self.assertEqual(result["reroute_reason"], "judge_payload_invalid")
        self.assertTrue(any("Codex judge unavailable" in item for item in result["findings"]))

    def test_codex_judge_transport_failure_is_signaled_explicitly(self) -> None:
        config = AppConfig(
            fmp_api_key=None,
            gemini_api_key=None,
            openai_api_key="test-key",
            codex_judge_model="gpt-5-codex",
        )
        result = codex_judge(
            {
                "ranked_candidates": [],
                "pending_human_review": [],
                "rejected_at_analysis_detail_packets": [],
                "current_holding_overlays": [],
            },
            {"entries": [], "candidate_count": 0, "survivor_count": 0},
            config=config,
            transport=lambda payload, app_config: (_ for _ in ()).throw(RuntimeError("network unavailable")),
        )

        self.assertEqual(result["verdict"], "REVISE")
        self.assertEqual(result["target_stage"], "report_assembly")
        self.assertEqual(result["reroute_reason"], "judge_transport_unavailable")
        self.assertTrue(any("network unavailable" in item for item in result["findings"]))

    def test_codex_judge_accepts_valid_transport_output(self) -> None:
        config = AppConfig(
            fmp_api_key=None,
            gemini_api_key=None,
            openai_api_key="test-key",
            codex_judge_model="gpt-5-codex",
        )
        result = codex_judge(
            {
                "ranked_candidates": [],
                "pending_human_review": [],
                "rejected_at_analysis_detail_packets": [],
                "current_holding_overlays": [],
            },
            {"entries": [], "candidate_count": 0, "survivor_count": 0},
            config=config,
            transport=lambda payload, app_config: {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "{\"verdict\": \"REVISE\", \"target_stage\": \"report_assembly\", \"findings\": [\"Need richer evidence.\"], \"reroute_reason\": \"judge_payload_invalid\"}",
                            }
                        ],
                    }
                ]
            },
        )

        self.assertEqual(result["verdict"], "REVISE")
        self.assertEqual(result["target_stage"], "report_assembly")
        self.assertEqual(result["reroute_reason"], "judge_payload_invalid")

    def test_raw_bundle_to_scan_to_judge_contract(self) -> None:
        raw_input_path = FIXTURES_ROOT / "ranked_candidate_bundle.json"
        scan_input = build_scan_input_file(raw_input_path)
        artifacts = run_scan(scan_input)
        result = validate_judge_result(artifacts.judge)

        self.assertEqual(result["verdict"], "APPROVE")


if __name__ == "__main__":
    unittest.main()
