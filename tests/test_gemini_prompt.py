"""Tests for the v2 Gemini prompt upgrade: directives, entity context, provenance."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "gemini" / "golden_prompt_v2.txt"

_EMPTY_EVIDENCE: dict = {
    "research_notes": [],
    "catalyst_evidence": [],
    "risk_evidence": [],
    "management_observations": [],
    "compensation_evidence": [],
    "moat_observations": [],
    "precedent_observations": [],
    "epistemic_anchors": [],
}


def _capturing_transport(captured: list[dict]):
    """Returns a transport that records the payload and returns a minimal valid response."""
    def transport(url: str, headers: dict, payload: dict) -> dict:
        captured.append(payload)
        return {"text": json.dumps(_EMPTY_EVIDENCE)}
    return transport


class TestSearchDirectives(unittest.TestCase):
    """SEARCH_DIRECTIVES covers the 7 required signal categories."""

    def setUp(self):
        from edenfintech_scanner_bootstrap.gemini import SEARCH_DIRECTIVES
        self.directives = SEARCH_DIRECTIVES

    def test_directive_count(self):
        self.assertEqual(len(self.directives), 7)

    def _directive_texts(self):
        return " ".join(d for d, _ in self.directives).lower()

    def test_directive_credit_ratings(self):
        self.assertIn("fitch", self._directive_texts())

    def test_directive_debt_maturity(self):
        self.assertIn("debt maturity", self._directive_texts())

    def test_directive_customer_concentration(self):
        self.assertIn("top 5 customers", self._directive_texts())

    def test_directive_regulatory(self):
        self.assertIn("cms", self._directive_texts())

    def test_directive_insider(self):
        self.assertIn("form 4", self._directive_texts())

    def test_directive_compensation(self):
        self.assertIn("def 14a", self._directive_texts())

    def test_directive_competitive_landscape(self):
        self.assertIn("competitive landscape", self._directive_texts())

    def test_each_directive_has_target_array(self):
        from edenfintech_scanner_bootstrap.gemini import EVIDENCE_ARRAY_KEYS
        for directive, array_name in self.directives:
            self.assertIn(array_name, EVIDENCE_ARRAY_KEYS, f"directive targets unknown array: {array_name!r}")


class TestDirectiveToArrayMapping(unittest.TestCase):
    """Rendered prompt maps each directive to its target array."""

    def _render_prompt(self, **kwargs) -> str:
        from edenfintech_scanner_bootstrap.gemini import SEARCH_DIRECTIVES, _candidate_prompt
        return _candidate_prompt("OMI", "test question", "Healthcare", directives=SEARCH_DIRECTIVES, **kwargs)

    def test_risk_evidence_appears_in_directive_lines(self):
        prompt = self._render_prompt()
        self.assertIn("risk_evidence", prompt)

    def test_catalyst_evidence_appears_in_directive_lines(self):
        prompt = self._render_prompt()
        self.assertIn("catalyst_evidence", prompt)

    def test_management_observations_appears_in_directive_lines(self):
        prompt = self._render_prompt()
        self.assertIn("management_observations", prompt)

    def test_compensation_evidence_appears_in_directive_lines(self):
        prompt = self._render_prompt()
        self.assertIn("compensation_evidence", prompt)

    def test_moat_observations_appears_in_directive_lines(self):
        prompt = self._render_prompt()
        self.assertIn("moat_observations", prompt)

    def test_schema_reinforcement_block_present(self):
        prompt = self._render_prompt()
        self.assertIn("CRITICAL", prompt)
        self.assertIn("Do NOT create new arrays", prompt)
        self.assertIn("verdicts", prompt.lower())

    def test_debt_maturity_and_risk_evidence_in_same_directive_line(self):
        prompt = self._render_prompt()
        lines = prompt.splitlines()
        debt_line = next((l for l in lines if "debt maturity" in l.lower()), None)
        self.assertIsNotNone(debt_line, "no line mentioning debt maturity")
        self.assertIn("risk_evidence", debt_line)


class TestEntityInterpolation(unittest.TestCase):
    """FMP-derived context entities appear in rendered prompt."""

    def _render_with_entities(self) -> str:
        from edenfintech_scanner_bootstrap.gemini import _candidate_prompt
        entities = {
            "company_name": "Accendra Health Inc",
            "sector": "Healthcare",
            "industry": "Medical Distribution",
            "description_excerpt": "A home-based care platform.",
        }
        return _candidate_prompt("OMI", "test question", "Healthcare", entities=entities)

    def test_company_name_in_prompt(self):
        self.assertIn("Accendra Health Inc", self._render_with_entities())

    def test_sector_in_prompt(self):
        self.assertIn("Healthcare", self._render_with_entities())

    def test_industry_in_prompt(self):
        self.assertIn("Medical Distribution", self._render_with_entities())


class TestProvenanceRoundTrip(unittest.TestCase):
    """search_directives and context_entities survive the build → validate cycle."""

    def _build_bundle(self, context_entities=None) -> dict:
        from edenfintech_scanner_bootstrap.gemini import GeminiClient, build_gemini_bundle
        captured: list[dict] = []
        client = GeminiClient("fake-key", transport=_capturing_transport(captured))
        return build_gemini_bundle(
            ["OMI"],
            client=client,
            context_entities=context_entities,
        )

    def test_search_directives_in_prompt_context(self):
        bundle = self._build_bundle()
        ctx = bundle["raw_candidates"][0]["gemini_context"]["prompt_context"]
        self.assertIn("search_directives", ctx)
        self.assertEqual(len(ctx["search_directives"]), 7)

    def test_search_directives_contain_array_annotations(self):
        bundle = self._build_bundle()
        ctx = bundle["raw_candidates"][0]["gemini_context"]["prompt_context"]
        for entry in ctx["search_directives"]:
            self.assertIn("→", entry, f"directive missing → mapping: {entry!r}")

    def test_context_entities_in_prompt_context(self):
        entities = {"OMI": {"company_name": "Accendra Health Inc", "sector": "Healthcare"}}
        bundle = self._build_bundle(context_entities=entities)
        ctx = bundle["raw_candidates"][0]["gemini_context"]["prompt_context"]
        self.assertIn("context_entities", ctx)
        self.assertEqual(ctx["context_entities"]["company_name"], "Accendra Health Inc")

    def test_bundle_passes_shape_validation(self):
        from edenfintech_scanner_bootstrap.gemini import _validate_gemini_bundle_shape
        bundle = self._build_bundle()
        _validate_gemini_bundle_shape(bundle)

    def test_no_new_keys_when_no_context_entities(self):
        bundle = self._build_bundle()
        ctx = bundle["raw_candidates"][0]["gemini_context"]["prompt_context"]
        self.assertNotIn("context_entities", ctx)


class TestBackwardCompat(unittest.TestCase):
    """Calling _candidate_prompt without new kwargs preserves existing behaviour."""

    def test_old_signature_still_works(self):
        from edenfintech_scanner_bootstrap.gemini import _candidate_prompt
        prompt = _candidate_prompt("OMI", "test question", "Healthcare")
        self.assertIn("compensation", prompt.lower())
        self.assertIn("proxy", prompt.lower())

    def test_old_build_bundle_still_validates(self):
        from edenfintech_scanner_bootstrap.gemini import GeminiClient, build_gemini_bundle, _validate_gemini_bundle_shape
        captured: list[dict] = []
        client = GeminiClient("fake-key", transport=_capturing_transport(captured))
        bundle = build_gemini_bundle(["OMI"], client=client)
        _validate_gemini_bundle_shape(bundle)


class TestStrategyRulesCoupling(unittest.TestCase):
    """SEARCH_DIRECTIVES anchor phrases align with strategy-rules.md."""

    def _rules_text(self) -> str:
        rules_path = Path(__file__).parent.parent / "assets" / "methodology" / "strategy-rules.md"
        if not rules_path.exists():
            self.skipTest("strategy-rules.md not found")
        return rules_path.read_text().lower()

    def test_customer_concentration_in_rules(self):
        self.assertIn("customer concentration", self._rules_text())

    def test_def_14a_or_compensation_in_rules(self):
        rules = self._rules_text()
        self.assertTrue(
            "def 14a" in rules or "compensation" in rules,
            "strategy-rules.md should mention compensation or DEF 14A",
        )


class TestGoldenPrompt(unittest.TestCase):
    """Canonical rendered prompt is locked via a golden file."""

    def _render_golden_prompt(self) -> str:
        from edenfintech_scanner_bootstrap.gemini import SEARCH_DIRECTIVES, _candidate_prompt
        entities = {
            "company_name": "Acme Corp",
            "sector": "Healthcare",
            "industry": "Medical Distribution",
        }
        return _candidate_prompt(
            "ACME",
            "Collect sourced qualitative research evidence relevant to this scan.",
            "ACME",
            entities=entities,
            directives=SEARCH_DIRECTIVES,
        )

    def test_golden_prompt(self):
        rendered = self._render_golden_prompt()
        if not GOLDEN_PATH.exists():
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(rendered)
            self.skipTest("Golden file created — re-run to validate.")
        expected = GOLDEN_PATH.read_text()
        self.assertEqual(rendered, expected, "Prompt changed vs golden file. Update golden_prompt_v2.txt if intentional.")


if __name__ == "__main__":
    unittest.main()
