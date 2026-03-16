"""Tests for provenance deduplication in repair and validation steps."""

import unittest


class TestEnsureProvenanceDedup(unittest.TestCase):
    """Verify _ensure_provenance_completeness deduplicates LLM-emitted duplicates."""

    def test_llm_duplicates_reduced_to_first(self):
        """When LLM emits multiple provenance entries for same field_path, keep first."""
        from edenfintech_scanner_bootstrap.analyst import _ensure_provenance_completeness

        synthesis = {
            "field_provenance": [
                {"field_path": "analysis_inputs.catalyst_classification",
                 "status": "LLM_DRAFT", "rationale": "first rationale",
                 "review_note": "first note", "evidence_refs": []},
                {"field_path": "analysis_inputs.catalyst_classification",
                 "status": "LLM_DRAFT", "rationale": "second rationale",
                 "review_note": "second note", "evidence_refs": []},
                {"field_path": "analysis_inputs.catalyst_classification",
                 "status": "LLM_DRAFT", "rationale": "third rationale",
                 "review_note": "third note", "evidence_refs": []},
                {"field_path": "analysis_inputs.dominant_risk_type",
                 "status": "LLM_DRAFT", "rationale": "only one",
                 "review_note": "unique", "evidence_refs": []},
            ],
        }
        _ensure_provenance_completeness(synthesis, {}, {})

        paths = [e["field_path"] for e in synthesis["field_provenance"]]
        # catalyst_classification should appear exactly once
        self.assertEqual(paths.count("analysis_inputs.catalyst_classification"), 1)
        # the kept entry should be the first one
        cc_entry = next(e for e in synthesis["field_provenance"]
                        if e["field_path"] == "analysis_inputs.catalyst_classification")
        self.assertIn("first", cc_entry["review_note"])

    def test_no_duplicates_not_reduced(self):
        """Clean provenance list has no entries dropped by dedup pass."""
        from edenfintech_scanner_bootstrap.analyst import _ensure_provenance_completeness

        synthesis = {
            "field_provenance": [
                {"field_path": "screening_inputs.solvency",
                 "status": "LLM_DRAFT", "rationale": "ok",
                 "review_note": "ok", "evidence_refs": []},
                {"field_path": "screening_inputs.dilution",
                 "status": "LLM_DRAFT", "rationale": "ok",
                 "review_note": "ok", "evidence_refs": []},
            ],
        }
        original_count = len(synthesis["field_provenance"])
        _ensure_provenance_completeness(synthesis, {}, {})
        # Repair step may add synthetic entries for missing required fields,
        # but no entries should have been DROPPED by dedup
        final_paths = [e["field_path"] for e in synthesis["field_provenance"]]
        # Both originals still present
        self.assertIn("screening_inputs.solvency", final_paths)
        self.assertIn("screening_inputs.dilution", final_paths)
        # No path appears more than once
        from collections import Counter
        counts = Counter(final_paths)
        duplicates = {p: c for p, c in counts.items() if c > 1}
        self.assertEqual(duplicates, {}, f"Unexpected duplicates: {duplicates}")


class TestValidateProvenanceDedup(unittest.TestCase):
    """Verify _validate_provenance_coverage deduplicates instead of crashing."""

    def test_duplicate_provenance_deduped_not_crashed(self):
        """Duplicate field_path in provenance should be deduped, not crash on duplicates."""
        from edenfintech_scanner_bootstrap.structured_analysis import (
            _validate_provenance_coverage, REQUIRED_PROVENANCE_FIELDS,
        )

        # Build a full provenance list with all required fields to avoid
        # the missing-fields check, then add a duplicate for one field.
        prov = []
        for fp in REQUIRED_PROVENANCE_FIELDS:
            prov.append({"field_path": fp, "status": "LLM_DRAFT",
                         "rationale": "ok", "review_note": "ok", "evidence_refs": []})
        # Add a duplicate
        prov.append({"field_path": "analysis_inputs.catalyst_classification",
                     "status": "LLM_DRAFT", "rationale": "duplicate",
                     "review_note": "duplicate", "evidence_refs": []})

        candidate = {"ticker": "TEST", "field_provenance": prov}

        # Should NOT raise ValueError for duplicates
        _validate_provenance_coverage(
            candidate,
            allow_machine_draft=True,
            require_review_note_for_finalized=False,
        )
        # Should have deduped
        paths = [e["field_path"] for e in candidate["field_provenance"]]
        self.assertEqual(paths.count("analysis_inputs.catalyst_classification"), 1)
        # First entry kept (rationale="ok"), not the duplicate
        cc = next(e for e in candidate["field_provenance"]
                  if e["field_path"] == "analysis_inputs.catalyst_classification")
        self.assertEqual(cc["rationale"], "ok")


if __name__ == "__main__":
    unittest.main()
