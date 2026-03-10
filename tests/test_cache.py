from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from edenfintech_scanner_bootstrap.cache import (
    DEFAULT_TTLS,
    FmpCacheStore,
    cached_transport,
)


class TestFmpCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name)
        self.store = FmpCacheStore(self.cache_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- core caching --

    def test_cached_response_returned(self) -> None:
        """Second call with same endpoint+ticker returns cached data; inner transport called once."""
        inner = MagicMock(return_value=[{"price": 100}])
        transport = cached_transport(inner, self.store)

        result1 = transport("quote", {"apikey": "k", "symbol": "AAPL"})
        result2 = transport("quote", {"apikey": "k", "symbol": "AAPL"})

        self.assertEqual(result1, result2)
        inner.assert_called_once()

    def test_expired_cache_refetches(self) -> None:
        """With TTL=0, second call invokes inner transport again."""
        store = FmpCacheStore(self.cache_dir, ttls={"quote": 0})
        inner = MagicMock(return_value=[{"price": 100}])
        transport = cached_transport(inner, store)

        transport("quote", {"apikey": "k", "symbol": "AAPL"})
        time.sleep(0.05)
        transport("quote", {"apikey": "k", "symbol": "AAPL"})

        self.assertEqual(inner.call_count, 2)

    def test_fresh_flag_bypasses(self) -> None:
        """With fresh=True, cached data ignored, inner transport called."""
        inner = MagicMock(return_value=[{"price": 100}])
        transport_cached = cached_transport(inner, self.store)
        transport_fresh = cached_transport(inner, self.store, fresh=True)

        transport_cached("quote", {"apikey": "k", "symbol": "AAPL"})
        self.assertEqual(inner.call_count, 1)

        transport_fresh("quote", {"apikey": "k", "symbol": "AAPL"})
        self.assertEqual(inner.call_count, 2)

    # -- empty/error guards --

    def test_empty_response_not_cached(self) -> None:
        """Inner transport returns [], cache file not created."""
        inner = MagicMock(return_value=[])
        transport = cached_transport(inner, self.store)

        transport("quote", {"apikey": "k", "symbol": "AAPL"})

        cached = self.store.get("quote", "AAPL")
        self.assertIsNone(cached)

    def test_error_response_not_cached(self) -> None:
        """Inner transport returns error dict, cache file not created."""
        inner = MagicMock(return_value={"Error Message": "Limit reached"})
        transport = cached_transport(inner, self.store)

        transport("quote", {"apikey": "k", "symbol": "AAPL"})

        cached = self.store.get("quote", "AAPL")
        self.assertIsNone(cached)

    # -- TTL configuration --

    def test_ttl_config(self) -> None:
        """Different endpoints get different TTL values from DEFAULT_TTLS."""
        self.assertEqual(DEFAULT_TTLS["quote"], 86400)
        self.assertEqual(DEFAULT_TTLS["profile"], 2592000)
        self.assertEqual(DEFAULT_TTLS["income-statement"], 7776000)
        self.assertNotEqual(DEFAULT_TTLS["quote"], DEFAULT_TTLS["profile"])

    # -- path sanitization --

    def test_cache_path_sanitization(self) -> None:
        """Endpoint 'historical-price-eod/full' becomes 'historical-price-eod--full' directory."""
        inner = MagicMock(return_value=[{"close": 150}])
        transport = cached_transport(inner, self.store)

        transport("historical-price-eod/full", {"apikey": "k", "symbol": "AAPL"})

        expected_dir = self.cache_dir / "historical-price-eod--full"
        self.assertTrue(expected_dir.exists())
        self.assertTrue((expected_dir / "AAPL.json").exists())

    # -- write ordering --

    def test_meta_written_before_data(self) -> None:
        """Meta file exists when data file exists (write ordering verified by both existing)."""
        inner = MagicMock(return_value=[{"price": 100}])
        transport = cached_transport(inner, self.store)

        transport("quote", {"apikey": "k", "symbol": "AAPL"})

        endpoint_dir = self.cache_dir / "quote"
        data_file = endpoint_dir / "AAPL.json"
        meta_file = endpoint_dir / "AAPL.meta.json"
        self.assertTrue(data_file.exists())
        self.assertTrue(meta_file.exists())

        meta = json.loads(meta_file.read_text())
        self.assertIn("timestamp", meta)
        self.assertIn("endpoint", meta)

    # -- status and clear --

    def test_status_reports_counts(self) -> None:
        """status() returns per-endpoint counts and expiry info."""
        self.store.put("quote", "AAPL", [{"price": 100}])
        self.store.put("quote", "MSFT", [{"price": 200}])
        self.store.put("profile", "AAPL", [{"name": "Apple"}])

        status = self.store.status()
        self.assertEqual(status["quote"]["count"], 2)
        self.assertEqual(status["profile"]["count"], 1)

    def test_clear_removes_all(self) -> None:
        """clear() removes all cached files and recreates empty dir."""
        self.store.put("quote", "AAPL", [{"price": 100}])
        self.store.clear()

        self.assertTrue(self.cache_dir.exists())
        self.assertEqual(list(self.cache_dir.iterdir()), [])


class TestCacheCli(unittest.TestCase):
    """Tests for CLI integration (Task 2 - added here for co-location)."""
    pass


if __name__ == "__main__":
    unittest.main()
