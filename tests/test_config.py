"""Tests for config.py secret loading logic."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from edenfintech_scanner_bootstrap.config import (
    _load_dotenv_text,
    _parse_dotenv_line,
    load_secrets,
)


class TestParseDotenvLine(unittest.TestCase):
    def test_simple_key_value(self):
        self.assertEqual(_parse_dotenv_line("FOO=bar"), ("FOO", "bar"))

    def test_quoted_value(self):
        self.assertEqual(_parse_dotenv_line('FOO="bar baz"'), ("FOO", "bar baz"))

    def test_single_quoted_value(self):
        self.assertEqual(_parse_dotenv_line("FOO='bar baz'"), ("FOO", "bar baz"))

    def test_empty_value(self):
        self.assertEqual(_parse_dotenv_line("FOO="), ("FOO", ""))

    def test_comment_line(self):
        self.assertIsNone(_parse_dotenv_line("# this is a comment"))

    def test_blank_line(self):
        self.assertIsNone(_parse_dotenv_line(""))


class TestLoadDotenvText(unittest.TestCase):
    def test_injects_into_environ(self):
        env_text = "TEST_AGE_KEY_A=alpha\nTEST_AGE_KEY_B=beta\n"
        try:
            _load_dotenv_text(env_text)
            self.assertEqual(os.environ["TEST_AGE_KEY_A"], "alpha")
            self.assertEqual(os.environ["TEST_AGE_KEY_B"], "beta")
        finally:
            os.environ.pop("TEST_AGE_KEY_A", None)
            os.environ.pop("TEST_AGE_KEY_B", None)

    def test_does_not_override_existing(self):
        os.environ["TEST_AGE_KEY_C"] = "original"
        try:
            _load_dotenv_text("TEST_AGE_KEY_C=replaced")
            self.assertEqual(os.environ["TEST_AGE_KEY_C"], "original")
        finally:
            os.environ.pop("TEST_AGE_KEY_C", None)

    def test_override_flag(self):
        os.environ["TEST_AGE_KEY_D"] = "original"
        try:
            _load_dotenv_text("TEST_AGE_KEY_D=replaced", override=True)
            self.assertEqual(os.environ["TEST_AGE_KEY_D"], "replaced")
        finally:
            os.environ.pop("TEST_AGE_KEY_D", None)


class TestLoadSecrets(unittest.TestCase):
    def test_skips_when_env_already_set(self):
        """When FMP_API_KEY is already in env (deployment), load_secrets is a no-op."""
        os.environ["FMP_API_KEY"] = "already-set"
        try:
            result = load_secrets()
            self.assertIsNone(result)
        finally:
            os.environ.pop("FMP_API_KEY", None)

    @patch("edenfintech_scanner_bootstrap.config.discover_age_path")
    @patch("edenfintech_scanner_bootstrap.config.discover_dotenv_path")
    def test_falls_back_to_dotenv(self, mock_dotenv, mock_age):
        """When no .env.age exists, falls back to .env."""
        os.environ.pop("FMP_API_KEY", None)
        mock_age.return_value = None

        tmp = Path("/tmp/test_fallback.env")
        tmp.write_text("FMP_API_KEY=fallback-key\n")
        mock_dotenv.return_value = tmp
        try:
            result = load_secrets()
            self.assertEqual(result, tmp)
            self.assertEqual(os.environ["FMP_API_KEY"], "fallback-key")
        finally:
            os.environ.pop("FMP_API_KEY", None)
            tmp.unlink(missing_ok=True)


class TestTemperatureConfig(unittest.TestCase):
    """Verify temperature fields load from env with correct defaults."""

    def test_defaults(self):
        from edenfintech_scanner_bootstrap.config import AppConfig
        config = AppConfig(
            fmp_api_key=None, gemini_api_key=None, openai_api_key=None,
            codex_judge_model="test",
        )
        self.assertEqual(config.analyst_temperature, 0.0)
        self.assertEqual(config.adversarial_temperature, 0.6)
        self.assertEqual(config.reviewer_temperature, 0.2)

    def test_env_override(self):
        from edenfintech_scanner_bootstrap.config import load_config
        os.environ["FMP_API_KEY"] = "test"
        os.environ["ANALYST_TEMPERATURE"] = "0.1"
        os.environ["ADVERSARIAL_TEMPERATURE"] = "0.8"
        os.environ["REVIEWER_TEMPERATURE"] = "0.3"
        try:
            config = load_config()
            self.assertAlmostEqual(config.analyst_temperature, 0.1)
            self.assertAlmostEqual(config.adversarial_temperature, 0.8)
            self.assertAlmostEqual(config.reviewer_temperature, 0.3)
        finally:
            os.environ.pop("ANALYST_TEMPERATURE", None)
            os.environ.pop("ADVERSARIAL_TEMPERATURE", None)
            os.environ.pop("REVIEWER_TEMPERATURE", None)
            os.environ.pop("FMP_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
