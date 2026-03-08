from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.assets import load_json
from edenfintech_scanner_bootstrap.structured_analysis import (
    apply_review_note_updates,
    render_review_structured_analysis_markdown,
    review_structured_analysis,
    review_structured_analysis_file,
    render_review_note_suggestions_markdown,
    suggest_review_notes,
    suggest_review_notes_file,
)


DRAFT_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "generated" / "merged_candidate_draft_overlay.json"


class ReviewHelperTest(unittest.TestCase):
    def test_review_report_flags_machine_drafts_and_missing_notes(self) -> None:
        payload = load_json(DRAFT_FIXTURE_PATH)

        report = review_structured_analysis(payload)

        self.assertFalse(report["ready_for_finalization"])
        self.assertEqual(report["summary"]["machine_draft"], 26)
        self.assertEqual(report["summary"]["missing_review_notes"], 26)
        self.assertEqual(report["candidates"][0]["entries"][0]["status"], "MACHINE_DRAFT")
        self.assertTrue(report["candidates"][0]["entries"][0]["needs_review_note"])

    def test_apply_review_note_updates_changes_only_targeted_note(self) -> None:
        payload = load_json(DRAFT_FIXTURE_PATH)
        original_evidence = payload["structured_candidates"][0]["screening_inputs"]["solvency"]["evidence"]

        updated = apply_review_note_updates(
            payload,
            [
                {
                    "field_path": "screening_inputs.solvency",
                    "review_note": "Reviewer checked solvency against cash generation history.",
                }
            ],
        )

        candidate = updated["structured_candidates"][0]
        provenance_by_path = {item["field_path"]: item for item in candidate["field_provenance"]}
        self.assertEqual(
            provenance_by_path["screening_inputs.solvency"]["review_note"],
            "Reviewer checked solvency against cash generation history.",
        )
        self.assertNotIn("review_note", provenance_by_path["screening_inputs.valuation"])
        self.assertEqual(candidate["screening_inputs"]["solvency"]["evidence"], original_evidence)

    def test_review_structured_analysis_file_writes_report_and_updated_overlay(self) -> None:
        payload = load_json(DRAFT_FIXTURE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            overlay_path = Path(tmpdir) / "overlay.json"
            report_path = Path(tmpdir) / "review-report.json"
            markdown_path = Path(tmpdir) / "review-report.md"
            updated_overlay_path = Path(tmpdir) / "overlay-reviewed.json"
            overlay_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            report = review_structured_analysis_file(
                overlay_path,
                json_out=report_path,
                markdown_out=markdown_path,
                overlay_out=updated_overlay_path,
                note_updates=[
                    {
                        "field_path": "screening_inputs.solvency",
                        "review_note": "Reviewer checked solvency against cash generation history.",
                    }
                ],
            )

            self.assertTrue(report_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertTrue(updated_overlay_path.exists())
            self.assertEqual(report["summary"]["missing_review_notes"], 25)
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Structured Analysis Review Checklist", markdown)
            self.assertIn("## RAW1", markdown)
            self.assertIn("### Required Provenance Entries", markdown)
            self.assertIn("`screening_inputs.solvency`", markdown)

    def test_review_structured_analysis_file_requires_overlay_out_for_note_updates(self) -> None:
        payload = load_json(DRAFT_FIXTURE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            overlay_path = Path(tmpdir) / "overlay.json"
            overlay_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "overlay_out is required when note_updates are provided"):
                review_structured_analysis_file(
                    overlay_path,
                    note_updates=[
                        {
                            "field_path": "screening_inputs.solvency",
                            "review_note": "Reviewer checked solvency against cash generation history.",
                        }
                    ],
                )

    def test_render_review_structured_analysis_markdown_contains_checklist_sections(self) -> None:
        payload = load_json(DRAFT_FIXTURE_PATH)
        report = review_structured_analysis(payload)

        markdown = render_review_structured_analysis_markdown(report)

        self.assertIn("# Structured Analysis Review Checklist", markdown)
        self.assertIn("## Summary", markdown)
        self.assertIn("## RAW1", markdown)
        self.assertIn("MACHINE_DRAFT", markdown)
        self.assertIn("missing review_note", markdown)

    def test_suggest_review_notes_only_covers_missing_entries(self) -> None:
        payload = load_json(DRAFT_FIXTURE_PATH)
        payload["structured_candidates"][0]["field_provenance"][0]["review_note"] = "Already reviewed."

        report = suggest_review_notes(payload)

        self.assertEqual(report["total_suggestions"], 25)
        first_candidate = report["candidates"][0]
        field_paths = {item["field_path"] for item in first_candidate["suggestions"]}
        self.assertNotIn("screening_inputs.industry_understandable", field_paths)
        self.assertIn("screening_inputs.solvency", field_paths)

    def test_render_review_note_suggestions_markdown_contains_sections(self) -> None:
        report = suggest_review_notes(load_json(DRAFT_FIXTURE_PATH))

        markdown = render_review_note_suggestions_markdown(report)

        self.assertIn("# Review Note Suggestions", markdown)
        self.assertIn("## RAW1", markdown)
        self.assertIn("Suggested note:", markdown)
        self.assertIn("`screening_inputs.solvency`", markdown)

    def test_suggest_review_notes_file_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            overlay_path = Path(tmpdir) / "overlay.json"
            json_out = Path(tmpdir) / "review-note-suggestions.json"
            markdown_out = Path(tmpdir) / "review-note-suggestions.md"
            overlay_path.write_text(json.dumps(load_json(DRAFT_FIXTURE_PATH), indent=2), encoding="utf-8")

            report = suggest_review_notes_file(
                overlay_path,
                json_out=json_out,
                markdown_out=markdown_out,
            )

            self.assertTrue(json_out.exists())
            self.assertTrue(markdown_out.exists())
            self.assertEqual(report["total_suggestions"], 26)


if __name__ == "__main__":
    unittest.main()
