"""Tests for thesis anchoring regex — false positive fixes."""
import unittest
from edenfintech_scanner_bootstrap.hardening import _THESIS_ANCHORING_PATTERN


class TestThesisAnchoringPattern(unittest.TestCase):
    """Probability anchoring regex should only match probability-related decimals."""

    def test_financial_ratio_not_flagged(self):
        """'interest coverage = 0.26' → no match for the decimal."""
        text = "interest coverage = 0.26"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        self.assertIsNone(match)

    def test_debt_equity_ratio_not_flagged(self):
        """'debt/equity ratio of 0.15' → no match."""
        text = "debt/equity ratio of 0.15"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        self.assertIsNone(match)

    def test_fcf_margin_not_flagged(self):
        """'FCF margin dropped to 0.02' → no match."""
        text = "FCF margin dropped to 0.02"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        self.assertIsNone(match)

    def test_probability_decimal_flagged(self):
        """'probability is 0.15' → match."""
        text = "probability is 0.15"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        self.assertIsNotNone(match)

    def test_likelihood_decimal_flagged(self):
        """'likelihood of 0.30' → match."""
        text = "likelihood of 0.30"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        self.assertIsNotNone(match)

    def test_reversed_decimal_probability_flagged(self):
        """'0.65 probability' → match."""
        text = "0.65 probability"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        self.assertIsNotNone(match)

    def test_percentage_still_flagged(self):
        """'15%' should still match."""
        text = "a 15% chance of failure"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        self.assertIsNotNone(match)

    def test_n_in_m_still_flagged(self):
        """'1 in 5' should still match."""
        text = "1 in 5 chance"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        self.assertIsNotNone(match)

    def test_word_percent_still_flagged(self):
        """'sixty percent' should still match."""
        text = "sixty percent chance"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        self.assertIsNotNone(match)

    def test_chance_decimal_flagged(self):
        """'chance of 0.45' → match."""
        text = "chance of 0.45"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        self.assertIsNotNone(match)

    def test_odds_decimal_flagged(self):
        """'odds at 0.7' → match."""
        text = "odds at 0.7"
        match = _THESIS_ANCHORING_PATTERN.search(text)
        # Note: 0.7 has only one digit after decimal - \d+ requires 1+, so this should match
        self.assertIsNotNone(match)


if __name__ == "__main__":
    unittest.main()
