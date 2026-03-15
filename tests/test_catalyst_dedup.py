"""Tests for catalyst deduplication prompt instruction."""
import unittest


class TestCatalystDedupInstruction(unittest.TestCase):
    """Verify synthesis prompt includes catalyst dedup instruction."""

    def test_synthesis_prompt_includes_dedup_instruction(self):
        """Stage 3 synthesis prompt must instruct catalyst deduplication."""
        from edenfintech_scanner_bootstrap.analyst import _build_synthesis_system_prompt
        prompt = _build_synthesis_system_prompt()
        self.assertIn("DEDUPLICATION", prompt)
        self.assertIn("catalysts array must not contain duplicate", prompt)

    def test_synthesis_prompt_prefers_sourced_version(self):
        """Dedup instruction must prefer the version with source citations."""
        from edenfintech_scanner_bootstrap.analyst import _build_synthesis_system_prompt
        prompt = _build_synthesis_system_prompt()
        self.assertIn("source citation", prompt.lower())

    def test_catalyst_stack_unaffected(self):
        """Dedup instruction must clarify catalyst_stack is separate."""
        from edenfintech_scanner_bootstrap.analyst import _build_synthesis_system_prompt
        prompt = _build_synthesis_system_prompt()
        self.assertIn("catalyst_stack", prompt)
        self.assertIn("unaffected", prompt)


if __name__ == "__main__":
    unittest.main()
