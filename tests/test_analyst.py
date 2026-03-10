"""Tests for the Claude analyst agent module.

Covers AGNT-01 through AGNT-05 requirements:
  AGNT-01: No __REQUIRED__ placeholders remain in output
  AGNT-02: All provenance entries have LLM_DRAFT status
  AGNT-03: All provenance entries have non-empty review_note citing sources
  AGNT-04: worst_case before base_case and bear before bull in raw response text
  AGNT-05: Output passes validate_structured_analysis
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.analyst import (
    ClaudeAnalystClient,
    _build_candidate_output_schema,
    _extract_evidence_snippets,
    _post_validate,
    _strip_unsupported_constraints,
    generate_llm_analysis_draft,
)
from edenfintech_scanner_bootstrap.assets import load_json
from edenfintech_scanner_bootstrap.structured_analysis import validate_structured_analysis

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
LLM_RESPONSE_FIXTURE = FIXTURE_DIR / "analyst" / "llm-response-fixture.json"
RAW_BUNDLE_FIXTURE = FIXTURE_DIR / "raw" / "merged_candidate_bundle.json"


def _fixture_transport(request_payload: dict) -> dict:
    """Mock transport that returns the fixture LLM response."""
    raw_text = LLM_RESPONSE_FIXTURE.read_text()
    return {"text": raw_text, "stop_reason": "end_turn"}


class TestStripUnsupportedConstraints(unittest.TestCase):
    """Tests for _strip_unsupported_constraints."""

    def test_removes_min_length(self):
        schema = {"type": "string", "minLength": 1}
        result = _strip_unsupported_constraints(schema)
        self.assertNotIn("minLength", result)

    def test_removes_minimum_maximum(self):
        schema = {"type": "number", "minimum": 0, "maximum": 100}
        result = _strip_unsupported_constraints(schema)
        self.assertNotIn("minimum", result)
        self.assertNotIn("maximum", result)

    def test_removes_min_max_items(self):
        schema = {"type": "array", "minItems": 1, "maxItems": 10, "items": {"type": "string"}}
        result = _strip_unsupported_constraints(schema)
        self.assertNotIn("minItems", result)
        self.assertNotIn("maxItems", result)

    def test_removes_max_length(self):
        schema = {"type": "string", "maxLength": 255}
        result = _strip_unsupported_constraints(schema)
        self.assertNotIn("maxLength", result)

    def test_adds_additional_properties_false_to_objects(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        result = _strip_unsupported_constraints(schema)
        self.assertFalse(result["additionalProperties"])

    def test_recursive_stripping(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "items": {"type": "array", "minItems": 1, "items": {"type": "number", "minimum": 0}},
            },
        }
        result = _strip_unsupported_constraints(schema)
        self.assertNotIn("minLength", result["properties"]["name"])
        self.assertNotIn("minItems", result["properties"]["items"])
        self.assertNotIn("minimum", result["properties"]["items"]["items"])


class TestBuildCandidateOutputSchema(unittest.TestCase):
    """Tests for _build_candidate_output_schema."""

    def test_returns_valid_json_schema(self):
        schema = _build_candidate_output_schema()
        self.assertEqual(schema["type"], "object")

    def test_required_sections(self):
        schema = _build_candidate_output_schema()
        required = schema["required"]
        for section in ["screening_inputs", "analysis_inputs", "epistemic_inputs", "field_provenance"]:
            self.assertIn(section, required)

    def test_no_unsupported_constraints(self):
        schema = _build_candidate_output_schema()
        schema_text = json.dumps(schema)
        # minLength could appear as a key name in the JSON, check via dict traversal
        self._assert_no_constraints(schema)

    def test_additional_properties_false_on_objects(self):
        schema = _build_candidate_output_schema()
        self._assert_additional_properties_false(schema)

    def test_provenance_status_enum_is_llm_draft_only(self):
        schema = _build_candidate_output_schema()
        prov_items = schema["properties"]["field_provenance"]["items"]
        status_enum = prov_items["properties"]["status"]["enum"]
        self.assertEqual(status_enum, ["LLM_DRAFT"])

    def _assert_no_constraints(self, schema: dict, path: str = "") -> None:
        if not isinstance(schema, dict):
            return
        for key in _strip_unsupported_constraints.__code__.co_consts:
            pass  # Just checking via the known set
        unsupported = {"minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"}
        for key in unsupported:
            self.assertNotIn(key, schema, f"Found {key} at {path}")
        for k, v in schema.items():
            if isinstance(v, dict):
                self._assert_no_constraints(v, f"{path}.{k}")
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        self._assert_no_constraints(item, f"{path}.{k}[{i}]")

    def _assert_additional_properties_false(self, schema: dict, path: str = "") -> None:
        if not isinstance(schema, dict):
            return
        if schema.get("type") == "object" and "properties" in schema:
            self.assertFalse(
                schema.get("additionalProperties", True),
                f"Missing additionalProperties:false at {path}",
            )
        for k, v in schema.items():
            if isinstance(v, dict):
                self._assert_additional_properties_false(v, f"{path}.{k}")


class TestExtractEvidenceSnippets(unittest.TestCase):
    """Tests for _extract_evidence_snippets."""

    def test_extracts_source_titles(self):
        raw_candidate = load_json(RAW_BUNDLE_FIXTURE)["raw_candidates"][0]
        titles = _extract_evidence_snippets(raw_candidate)
        self.assertIn("Earnings call", titles)
        self.assertIn("10-K", titles)
        self.assertIn("Investor deck", titles)

    def test_empty_on_no_gemini_context(self):
        titles = _extract_evidence_snippets({"ticker": "TEST"})
        self.assertEqual(titles, set())


class TestClaudeAnalystClient(unittest.TestCase):
    """Tests for ClaudeAnalystClient instantiation and analyze."""

    def test_instantiation_with_mock_transport(self):
        client = ClaudeAnalystClient("test-key", transport=_fixture_transport)
        self.assertEqual(client.api_key, "test-key")
        self.assertEqual(client.model, "claude-sonnet-4-5-20250514")

    def test_instantiation_custom_model(self):
        client = ClaudeAnalystClient("key", model="claude-opus-4-20250514", transport=_fixture_transport)
        self.assertEqual(client.model, "claude-opus-4-20250514")

    def test_analyze_returns_dict(self):
        raw_bundle = load_json(RAW_BUNDLE_FIXTURE)
        raw_candidate = raw_bundle["raw_candidates"][0]
        client = ClaudeAnalystClient("test-key", transport=_fixture_transport)
        result = client.analyze(raw_candidate)
        self.assertIsInstance(result, dict)
        self.assertIn("screening_inputs", result)
        self.assertIn("analysis_inputs", result)
        self.assertIn("epistemic_inputs", result)
        self.assertIn("field_provenance", result)

    def test_last_raw_response_stored(self):
        raw_bundle = load_json(RAW_BUNDLE_FIXTURE)
        raw_candidate = raw_bundle["raw_candidates"][0]
        client = ClaudeAnalystClient("test-key", transport=_fixture_transport)
        client.analyze(raw_candidate)
        self.assertIsNotNone(client._last_raw_response)
        self.assertIsInstance(client._last_raw_response, str)


class TestAnalystAgent(unittest.TestCase):
    """Integration tests for generate_llm_analysis_draft.

    Tests AGNT-01 through AGNT-05 requirements.
    """

    @classmethod
    def setUpClass(cls):
        cls.raw_bundle = load_json(RAW_BUNDLE_FIXTURE)
        client = ClaudeAnalystClient("test-key", transport=_fixture_transport)
        cls.overlay = generate_llm_analysis_draft(cls.raw_bundle, client=client)
        cls.client = client

    def test_agnt01_no_required_placeholders(self):
        """AGNT-01: No __REQUIRED__ placeholders remain in output."""
        overlay_text = json.dumps(self.overlay)
        self.assertNotIn("__REQUIRED__", overlay_text)

    def test_agnt02_all_provenance_llm_draft(self):
        """AGNT-02: All provenance entries have LLM_DRAFT status."""
        for candidate in self.overlay["structured_candidates"]:
            for item in candidate["field_provenance"]:
                self.assertEqual(
                    item["status"], "LLM_DRAFT",
                    f"Expected LLM_DRAFT for {item.get('field_path')}, got {item['status']}",
                )

    def test_agnt03_all_provenance_have_review_note(self):
        """AGNT-03: All provenance entries have non-empty review_note."""
        for candidate in self.overlay["structured_candidates"]:
            for item in candidate["field_provenance"]:
                review_note = item.get("review_note")
                self.assertIsInstance(review_note, str, f"review_note missing for {item.get('field_path')}")
                self.assertTrue(
                    review_note.strip(),
                    f"review_note empty for {item.get('field_path')}",
                )

    def test_agnt04_worst_case_before_base_case(self):
        """AGNT-04: worst_case appears before base_case in raw response text."""
        raw_text = LLM_RESPONSE_FIXTURE.read_text()
        wc_pos = raw_text.index("worst_case")
        bc_pos = raw_text.index("base_case")
        self.assertLess(
            wc_pos, bc_pos,
            f"worst_case at {wc_pos} must appear before base_case at {bc_pos}",
        )
        # Also verify _post_validate does not raise for this ordering
        candidate_output = json.loads(raw_text)
        raw_candidate = self.raw_bundle["raw_candidates"][0]
        _post_validate(candidate_output, raw_candidate, raw_text)

    def test_agnt04_bear_before_bull(self):
        """AGNT-04: bear appears before bull in raw response text."""
        raw_text = LLM_RESPONSE_FIXTURE.read_text()
        bear_pos = raw_text.index("bear")
        bull_pos = raw_text.index("bull")
        self.assertLess(
            bear_pos, bull_pos,
            f"bear at {bear_pos} must appear before bull at {bull_pos}",
        )

    def test_agnt05_passes_schema_validation(self):
        """AGNT-05: Overlay passes validate_structured_analysis."""
        # Will raise if validation fails
        validate_structured_analysis(self.overlay)

    def test_overlay_completion_status_is_draft(self):
        self.assertEqual(self.overlay["completion_status"], "DRAFT")

    def test_overlay_generation_metadata_source(self):
        self.assertEqual(self.overlay["generation_metadata"]["source"], "analyst.py")

    def test_post_validate_rejects_reversed_worst_base_order(self):
        """_post_validate raises when base_case appears before worst_case."""
        raw_text = '{"base_case": 1, "worst_case": 2}'
        with self.assertRaises(ValueError) as ctx:
            _post_validate({}, {}, raw_text)
        self.assertIn("worst_case must appear before base_case", str(ctx.exception))

    def test_post_validate_rejects_reversed_bear_bull_order(self):
        """_post_validate raises when bull appears before bear."""
        raw_text = '{"worst_case": 1, "base_case": 2, "bull": 3, "bear": 4}'
        with self.assertRaises(ValueError) as ctx:
            _post_validate({"field_provenance": []}, {}, raw_text)
        self.assertIn("bear must appear before bull", str(ctx.exception))

    def test_post_validate_rejects_placeholder(self):
        """_post_validate raises on __REQUIRED__ placeholder."""
        with self.assertRaises(ValueError) as ctx:
            _post_validate(
                {"field_provenance": [], "value": "__REQUIRED__"},
                {},
                '{"worst_case": 1, "base_case": 2}',
            )
        self.assertIn("__REQUIRED__", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
