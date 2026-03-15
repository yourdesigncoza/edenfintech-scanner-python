"""Tests for incentive alignment pipeline additions."""
import unittest


class TestGeminiCompensationEvidence(unittest.TestCase):
    """Verify compensation_evidence is wired into Gemini layer."""

    def test_evidence_array_keys_includes_compensation(self):
        """compensation_evidence must be in EVIDENCE_ARRAY_KEYS."""
        from edenfintech_scanner_bootstrap.gemini import EVIDENCE_ARRAY_KEYS
        self.assertIn("compensation_evidence", EVIDENCE_ARRAY_KEYS)

    def test_candidate_prompt_mentions_compensation(self):
        """_candidate_prompt must instruct Gemini to collect compensation data."""
        from edenfintech_scanner_bootstrap.gemini import _candidate_prompt
        prompt = _candidate_prompt("OMI", "test question", "Healthcare")
        self.assertIn("compensation", prompt.lower())
        self.assertIn("proxy", prompt.lower())

    def test_gemini_schema_includes_compensation_evidence(self):
        """gemini-raw-bundle.schema.json must include compensation_evidence."""
        from edenfintech_scanner_bootstrap.assets import gemini_raw_bundle_schema_path, load_json
        schema = load_json(gemini_raw_bundle_schema_path())
        context_props = schema["definitions"]["gemini_context"]["properties"]
        self.assertIn("compensation_evidence", context_props)
        required = schema["definitions"]["gemini_context"]["required"]
        self.assertIn("compensation_evidence", required)


class TestAnalystIncentiveAlignment(unittest.TestCase):
    """Verify incentive_alignment is in Stage 2 prompt and schema."""

    def test_qualitative_system_prompt_includes_incentive_alignment(self):
        """Stage 2 system prompt must list incentive_alignment."""
        from edenfintech_scanner_bootstrap.analyst import _build_qualitative_system_prompt
        prompt = _build_qualitative_system_prompt()
        self.assertIn("incentive_alignment", prompt)

    def test_structured_analysis_schema_includes_incentive_alignment(self):
        """structured-analysis.schema.json must define incentive_alignment object."""
        from edenfintech_scanner_bootstrap.assets import structured_analysis_schema_path, load_json
        schema = load_json(structured_analysis_schema_path())
        ai_props = schema["definitions"]["analysis_inputs"]["properties"]
        self.assertIn("incentive_alignment", ai_props)
        ia = ai_props["incentive_alignment"]
        self.assertEqual(ia["type"], "object")
        self.assertIn("pay_metric", ia["properties"])
        self.assertIn("gameable_risk", ia["properties"])
        self.assertIn("evidence_basis", ia["properties"])

    def test_gameable_risk_enum_values(self):
        """gameable_risk must have LOW/MODERATE/HIGH/UNKNOWN enum."""
        from edenfintech_scanner_bootstrap.assets import structured_analysis_schema_path, load_json
        schema = load_json(structured_analysis_schema_path())
        ia = schema["definitions"]["analysis_inputs"]["properties"]["incentive_alignment"]
        gr = ia["properties"]["gameable_risk"]
        self.assertEqual(sorted(gr["enum"]), ["HIGH", "LOW", "MODERATE", "UNKNOWN"])

    def test_qualitative_fields_tuple_includes_incentive_alignment(self):
        """incentive_alignment must be in _QUALITATIVE_ANALYSIS_FIELDS for constrained decoding."""
        from edenfintech_scanner_bootstrap.analyst import _QUALITATIVE_ANALYSIS_FIELDS
        self.assertIn("incentive_alignment", _QUALITATIVE_ANALYSIS_FIELDS)


if __name__ == "__main__":
    unittest.main()
