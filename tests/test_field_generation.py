from __future__ import annotations

import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.assets import load_json
from edenfintech_scanner_bootstrap.field_generation import build_structured_analysis_draft_file, generate_structured_analysis_draft


FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"


class FieldGenerationTest(unittest.TestCase):
    def test_generated_draft_matches_golden_fixture(self) -> None:
        raw_bundle = load_json(FIXTURES_ROOT / "raw" / "merged_candidate_bundle.json")
        expected = load_json(FIXTURES_ROOT / "generated" / "merged_candidate_draft_overlay.json")

        generated = generate_structured_analysis_draft(raw_bundle)

        self.assertEqual(generated, expected)

    def test_build_structured_analysis_draft_file_writes_json(self) -> None:
        draft = build_structured_analysis_draft_file(FIXTURES_ROOT / "raw" / "merged_candidate_bundle.json")

        self.assertEqual(draft["completion_status"], "DRAFT")
        self.assertEqual(draft["generation_metadata"]["source"], "field_generation.py")
        self.assertEqual(draft["structured_candidates"][0]["field_provenance"][0]["status"], "MACHINE_DRAFT")


if __name__ == "__main__":
    unittest.main()
