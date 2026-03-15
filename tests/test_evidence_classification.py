"""Tests for evidence URL classification — Gemini grounding URLs."""
import unittest
from edenfintech_scanner_bootstrap.epistemic_reviewer import is_weak_evidence


class TestEvidenceClassification(unittest.TestCase):
    """Evidence with URLs should be classified as concrete."""

    def test_vertexai_url_not_weak(self):
        """Gemini grounding URL → concrete (not weak)."""
        text = "Source: https://vertexaisearch.cloud.google.com/grounding-api-redirect/some-path"
        self.assertFalse(is_weak_evidence(text))

    def test_businesswire_not_weak(self):
        """businesswire domain → concrete."""
        text = "Per businesswire press release dated 2025-01-15"
        self.assertFalse(is_weak_evidence(text))

    def test_generic_url_not_weak(self):
        """Any https:// URL → concrete."""
        text = "According to https://example.com/some-report the revenue grew"
        self.assertFalse(is_weak_evidence(text))

    def test_truly_vague_still_flagged(self):
        """'analysts suggest' with no URL → still vague."""
        text = "analysts suggest the company will recover"
        self.assertTrue(is_weak_evidence(text))

    def test_morningstar_not_weak(self):
        """morningstar domain → concrete."""
        text = "Morningstar rates this fund 4 stars"
        self.assertFalse(is_weak_evidence(text))

    def test_spglobal_not_weak(self):
        """spglobal reference → concrete."""
        text = "spglobal credit rating downgrade"
        self.assertFalse(is_weak_evidence(text))

    def test_empty_not_weak(self):
        """Empty string → not weak (honest missing)."""
        self.assertFalse(is_weak_evidence(""))

    def test_no_evidence_not_weak(self):
        """NO_EVIDENCE → not weak (honest declaration)."""
        self.assertFalse(is_weak_evidence("NO_EVIDENCE"))

    def test_vague_no_url_still_weak(self):
        """'various sources indicate' with no concrete marker → weak."""
        text = "various sources indicate growth potential"
        self.assertTrue(is_weak_evidence(text))


if __name__ == "__main__":
    unittest.main()
