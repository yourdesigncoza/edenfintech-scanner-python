"""Tests for GeminiCacheStore prompt-version keying."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TestGeminiCachePromptVersion(unittest.TestCase):
    """Cache entries are isolated by prompt version so prompt upgrades auto-invalidate."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _store(self, prompt_version=None):
        from edenfintech_scanner_bootstrap.cache import GeminiCacheStore
        return GeminiCacheStore(self.cache_dir, prompt_version=prompt_version)

    def test_versioned_put_then_get_same_version(self):
        store = self._store("v2-test")
        store.put("OMI", {"evidence": "data"})
        result = store.get("OMI")
        self.assertIsNotNone(result)
        self.assertEqual(result["evidence"], "data")

    def test_versioned_entry_not_visible_from_different_version(self):
        store_v2 = self._store("v2-test")
        store_v2.put("OMI", {"evidence": "v2-data"})

        store_v3 = self._store("v3-test")
        result = store_v3.get("OMI")
        self.assertIsNone(result)

    def test_unversioned_put_not_visible_from_versioned_store(self):
        store_none = self._store(None)
        store_none.put("OMI", {"evidence": "unversioned"})

        store_v2 = self._store("v2-test")
        result = store_v2.get("OMI")
        self.assertIsNone(result)

    def test_versioned_filenames_contain_version_string(self):
        store = self._store("v2-test")
        store.put("OMI", {"x": 1})
        data_files = list(self.cache_dir.glob("OMI__v2-test*.json"))
        self.assertTrue(any(not f.name.endswith(".meta.json") for f in data_files))

    def test_status_ticker_parsed_correctly_for_versioned_entries(self):
        store = self._store("v2-test")
        store.put("OMI", {"x": 1})
        status = store.status()
        tickers = [e["ticker"] for e in status["entries"]]
        self.assertIn("OMI", tickers)

    def test_no_version_uses_legacy_filename(self):
        store = self._store(None)
        store.put("OMI", {"x": 1})
        self.assertTrue((self.cache_dir / "OMI.json").exists())
        self.assertTrue((self.cache_dir / "OMI.meta.json").exists())


if __name__ == "__main__":
    unittest.main()
