"""Tests for worst-case dilution/covenant prompt instructions."""
import unittest


class TestWorstCasePromptInstructions(unittest.TestCase):
    """Verify Stage 1 prompt instructs LLM to model dilution and covenant breach."""

    def test_prompt_instructs_dilution_modeling(self):
        """Stage 1 prompt must instruct dilution modeling when distressed."""
        from edenfintech_scanner_bootstrap.analyst import _build_fundamentals_system_prompt
        prompt = _build_fundamentals_system_prompt()
        self.assertIn("equity issuance", prompt.lower())
        self.assertIn("interest coverage", prompt.lower())
        self.assertIn("post-dilution", prompt.lower())

    def test_prompt_instructs_covenant_breach_modeling(self):
        """Stage 1 prompt must instruct covenant breach narrative in trough_path."""
        from edenfintech_scanner_bootstrap.analyst import _build_fundamentals_system_prompt
        prompt = _build_fundamentals_system_prompt()
        self.assertIn("covenant", prompt.lower())
        self.assertIn("trough_path", prompt)


if __name__ == "__main__":
    unittest.main()
