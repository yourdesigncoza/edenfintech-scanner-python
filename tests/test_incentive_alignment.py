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


if __name__ == "__main__":
    unittest.main()
