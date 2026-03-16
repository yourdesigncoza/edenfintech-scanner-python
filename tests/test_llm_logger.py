"""Tests for LLM logger model name fallback."""
import unittest
from edenfintech_scanner_bootstrap.llm_logger import LlmInteractionLog, wrap_transport


class TestWrapTransportModelName(unittest.TestCase):
    """wrap_transport model name resolution."""

    def _make_transport(self, response: dict):
        """Create a simple passthrough transport."""
        def transport(payload: dict) -> dict:
            return response
        return transport

    def test_model_name_fallback_used(self):
        """When payload has no 'model' key, model_name kwarg is used."""
        log = LlmInteractionLog()
        response = {"text": "ok", "stop_reason": "end"}
        wrapped = wrap_transport(
            self._make_transport(response), log, model_name="gpt-4o",
        )
        wrapped({"system": "test analyst", "messages": []})
        self.assertEqual(len(log._records), 1)
        self.assertEqual(log._records[0]["model"], "gpt-4o")

    def test_payload_model_takes_precedence(self):
        """When payload has 'model' key, it takes precedence over model_name."""
        log = LlmInteractionLog()
        response = {"text": "ok", "stop_reason": "end"}
        wrapped = wrap_transport(
            self._make_transport(response), log, model_name="gpt-4o",
        )
        wrapped({"model": "claude-haiku-4-5-20251001", "system": "test analyst", "messages": []})
        self.assertEqual(log._records[0]["model"], "claude-haiku-4-5-20251001")

    def test_unknown_when_no_model(self):
        """When neither payload nor model_name has model, falls back to 'unknown'."""
        log = LlmInteractionLog()
        response = {"text": "ok", "stop_reason": "end"}
        wrapped = wrap_transport(self._make_transport(response), log)
        wrapped({"system": "test", "messages": []})
        self.assertEqual(log._records[0]["model"], "unknown")


class TestWriteMarkdownElision(unittest.TestCase):
    """write_markdown elides duplicate fenced code blocks."""

    def _make_log_with_duplication(self, tmp_dir):
        """Build a log where a large block appears in two calls."""
        log = LlmInteractionLog()
        large_block = '{"sector": "' + "x" * 3000 + '"}'

        # Call 1: contains the large block in system prompt
        log.record(
            "analyst/fundamentals", "gpt-5-mini",
            {
                "system": f"Instructions here.\nSECTOR CONTEXT:\n{large_block}\nEnd.",
                "messages": [{"role": "user", "content": "Analyze ticker X."}],
            },
            {"text": '{"result": "ok"}', "stop_reason": "end_turn"},
        )
        # Call 2: same large block in system prompt
        log.record(
            "analyst/qualitative", "gpt-5-mini",
            {
                "system": f"More instructions.\nSECTOR CONTEXT:\n{large_block}\nEnd.",
                "messages": [{"role": "user", "content": "Qualitative analysis."}],
            },
            {"text": '{"result": "qual"}', "stop_reason": "end_turn"},
        )
        return log

    def test_duplicate_block_elided(self):
        """Second occurrence of a large code block is replaced with reference."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            log = self._make_log_with_duplication(tmp)
            path = log.write_markdown(Path(tmp))
            content = path.read_text()
            # Large block should appear once in full
            self.assertEqual(content.count("x" * 3000), 1)
            # Second occurrence should be elided
            self.assertIn("[ELIDED:", content)
            self.assertIn("Call 1", content)

    def test_response_blocks_never_elided(self):
        """Even if responses are identical, they are not elided."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            log = LlmInteractionLog()
            same_response = '{"verdict": "' + "y" * 3000 + '"}'
            for i in range(2):
                log.record(
                    f"agent_{i}", "model",
                    {"system": f"prompt {i}", "messages": []},
                    {"text": same_response, "stop_reason": "end_turn"},
                )
            path = log.write_markdown(Path(tmp))
            content = path.read_text()
            # Response should appear twice (never elided)
            self.assertEqual(content.count("y" * 3000), 2)
            self.assertNotIn("[ELIDED:", content)

    def test_small_blocks_not_elided(self):
        """Blocks under 2KB are never elided even if duplicated."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            log = LlmInteractionLog()
            small_block = '{"tiny": "data"}'
            for i in range(2):
                log.record(
                    f"agent_{i}", "model",
                    {"system": small_block, "messages": []},
                    {"text": "ok", "stop_reason": "end_turn"},
                )
            path = log.write_markdown(Path(tmp))
            content = path.read_text()
            self.assertNotIn("[ELIDED:", content)

    def test_evidence_context_elided_in_user_message(self):
        """EVIDENCE CONTEXT duplicated across user messages is elided."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            log = LlmInteractionLog()
            evidence = '{"market_snapshot": {"price": 2.68, "data": "' + "z" * 3000 + '"}}'
            for i in range(2):
                log.record(
                    f"agent_{i}", "model",
                    {
                        "system": f"stage {i} instructions",
                        "messages": [{"role": "user", "content": f"Ticker: X\n\nEVIDENCE CONTEXT:\n{evidence}\n\nEnd."}],
                    },
                    {"text": "ok", "stop_reason": "end_turn"},
                )
            path = log.write_markdown(Path(tmp))
            content = path.read_text()
            self.assertEqual(content.count("z" * 3000), 1)
            self.assertIn("[ELIDED:", content)

    def test_whole_content_fallback_elides_pure_json(self):
        """Pure JSON user messages (forwarded stage output) are elided via whole-content fallback."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            log = LlmInteractionLog()
            large_json = '{"overlay": "' + "w" * 5000 + '"}'
            # Call 1 produces it as a response (not elided)
            log.record(
                "analyst/synthesis", "model",
                {"system": "synth prompt", "messages": []},
                {"text": large_json, "stop_reason": "end_turn"},
            )
            # Call 2 receives it as user message (should be elided if identical)
            log.record(
                "validator/red_team", "model",
                {"system": "validator prompt", "messages": [{"role": "user", "content": large_json}]},
                {"text": "ok", "stop_reason": "end_turn"},
            )
            # Call 3 also receives it as user message (should also be elided)
            log.record(
                "validator/pre_mortem", "model",
                {"system": "pre-mortem prompt", "messages": [{"role": "user", "content": large_json}]},
                {"text": "ok", "stop_reason": "end_turn"},
            )
            path = log.write_markdown(Path(tmp))
            content = path.read_text()
            # Response appears once (never elided), first user message registers,
            # second user message should be elided
            self.assertIn("[ELIDED:", content)


class TestInferAgent(unittest.TestCase):
    """_infer_agent label inference from system prompts."""

    def test_analyst_fundamentals(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are a senior equity research analyst producing QUANTITATIVE FUNDAMENTALS ONLY."
        self.assertEqual(_infer_agent(prompt), "analyst/fundamentals")

    def test_analyst_qualitative(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are a senior equity research analyst producing QUALITATIVE ANALYSIS ONLY."
        self.assertEqual(_infer_agent(prompt), "analyst/qualitative")

    def test_analyst_synthesis(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are a senior equity research analyst producing a UNIFIED STRUCTURED ANALYSIS OVERLAY."
        self.assertEqual(_infer_agent(prompt), "analyst/synthesis")

    def test_analyst_with_epistemic_inputs_field(self):
        """Analyst prompts mentioning 'epistemic_inputs' as output field must NOT match epistemic_reviewer."""
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = (
            "You are a senior equity research analyst producing QUANTITATIVE FUNDAMENTALS ONLY.\n"
            "SCOPE: Produce screening_inputs, epistemic_inputs, and field_provenance."
        )
        self.assertEqual(_infer_agent(prompt), "analyst/fundamentals")

    def test_epistemic_reviewer(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are an independent epistemic reviewer for the EdenFinTech scan pipeline."
        self.assertEqual(_infer_agent(prompt), "epistemic_reviewer")

    def test_validator_red_team(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are a red-team adversarial reviewer."
        self.assertEqual(_infer_agent(prompt), "validator/red_team")

    def test_validator_pre_mortem(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "Run a pre-mortem analysis with thesis invalidation conditions."
        self.assertEqual(_infer_agent(prompt), "validator/pre_mortem")

    def test_cagr_exception(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are evaluating a CAGR exception candidate."
        self.assertEqual(_infer_agent(prompt), "hardening/cagr_exception")

    def test_unknown_fallback(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "Hello world."
        self.assertEqual(_infer_agent(prompt), "unknown")


class TestGeminiCacheHitRecord(unittest.TestCase):
    """Gemini cache hit inserts a synthetic log record."""

    def test_record_gemini_cache_hit(self):
        log = LlmInteractionLog()
        cached_data = {"raw_candidates": [{"ticker": "OMI", "catalyst_evidence": [{"claim": "test"}]}]}
        log.record_cache_hit("gemini/qualitative", "gemini-3-pro-preview", cached_data)
        self.assertEqual(len(log._records), 1)
        rec = log._records[0]
        self.assertEqual(rec["agent"], "gemini/qualitative")
        self.assertEqual(rec["model"], "gemini-3-pro-preview [CACHE HIT]")
        self.assertIn("CACHE HIT", rec["input"]["system"])


if __name__ == "__main__":
    unittest.main()
