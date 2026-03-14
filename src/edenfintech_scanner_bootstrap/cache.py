"""FMP response caching layer with per-endpoint TTLs."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from .fmp import FmpTransport


# Per-endpoint TTL in seconds
DEFAULT_TTLS: dict[str, int] = {
    "quote": 86_400,                    # 1 day
    "historical-price-eod/full": 86_400, # 1 day
    "profile": 2_592_000,               # 30 days
    "income-statement": 7_776_000,       # 90 days
    "cash-flow-statement": 7_776_000,    # 90 days
    "key-metrics": 604_800,             # 7 days
    "key-metrics-ttm": 604_800,         # 7 days
    "enterprise-values": 604_800,       # 7 days
    "ratios": 604_800,                  # 7 days
    # batch-quote removed: now uses standard "quote" endpoint with comma-separated symbols
    "stock-screener": 604_800,          # 7 days
    "stock-peers": 2_592_000,           # 30 days
}

_DEFAULT_TTL = 86_400  # fallback: 1 day


def _sanitize_endpoint(endpoint: str) -> str:
    """Replace '/' with '--' for filesystem-safe directory names."""
    return endpoint.replace("/", "--")


def _is_empty_or_error(data: Any) -> bool:
    """Return True if data is empty or an FMP error response."""
    if isinstance(data, list):
        return len(data) == 0
    if isinstance(data, dict):
        return len(data) == 0 or "Error Message" in data
    return False


class FmpCacheStore:
    """Disk-backed cache for FMP API responses, keyed by endpoint + ticker."""

    def __init__(self, cache_dir: Path, ttls: dict[str, int] | None = None) -> None:
        self.cache_dir = cache_dir
        self.ttls = ttls if ttls is not None else dict(DEFAULT_TTLS)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _ttl_for(self, endpoint: str) -> int:
        return self.ttls.get(endpoint, _DEFAULT_TTL)

    def _data_path(self, endpoint: str, ticker: str) -> Path:
        return self.cache_dir / _sanitize_endpoint(endpoint) / f"{ticker}.json"

    def _meta_path(self, endpoint: str, ticker: str) -> Path:
        return self.cache_dir / _sanitize_endpoint(endpoint) / f"{ticker}.meta.json"

    def get(self, endpoint: str, ticker: str) -> Any | None:
        """Return cached data if present and not expired, else None."""
        meta_path = self._meta_path(endpoint, ticker)
        data_path = self._data_path(endpoint, ticker)

        if not meta_path.exists() or not data_path.exists():
            return None

        meta = json.loads(meta_path.read_text())
        ttl = self._ttl_for(endpoint)
        age = time.time() - meta["timestamp"]
        if age > ttl:
            return None

        return json.loads(data_path.read_text())

    def put(self, endpoint: str, ticker: str, data: Any) -> None:
        """Write data and meta sidecar to cache. Meta written first."""
        if _is_empty_or_error(data):
            return

        endpoint_dir = self.cache_dir / _sanitize_endpoint(endpoint)
        endpoint_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "endpoint": endpoint,
            "ticker": ticker,
            "timestamp": time.time(),
        }

        # Write ordering: meta first, then data (per research pitfall 3)
        self._meta_path(endpoint, ticker).write_text(json.dumps(meta, indent=2))
        self._data_path(endpoint, ticker).write_text(json.dumps(data, indent=2))

    def status(self) -> dict[str, dict]:
        """Walk cache_dir, count entries per endpoint, report TTL expiry dates."""
        result: dict[str, dict] = {}
        if not self.cache_dir.exists():
            return result

        for endpoint_dir in sorted(self.cache_dir.iterdir()):
            if not endpoint_dir.is_dir():
                continue
            data_files = list(endpoint_dir.glob("*.json"))
            # Exclude .meta.json files from count
            data_files = [f for f in data_files if not f.name.endswith(".meta.json")]
            if not data_files:
                continue

            # Restore original endpoint name from sanitized dir name
            endpoint_name = endpoint_dir.name.replace("--", "/")
            ttl = self._ttl_for(endpoint_name)
            tickers: list[dict] = []
            for data_file in sorted(data_files):
                ticker = data_file.stem
                meta_path = endpoint_dir / f"{ticker}.meta.json"
                expires_at = None
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text())
                    expires_at = meta["timestamp"] + ttl
                tickers.append({"ticker": ticker, "expires_at": expires_at})

            result[endpoint_name] = {
                "count": len(data_files),
                "ttl_seconds": ttl,
                "entries": tickers,
            }
        return result

    def clear(self) -> None:
        """Remove all cached files and recreate empty cache_dir."""
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


GEMINI_DEFAULT_TTL = 14_400  # 4 hours


class GeminiCacheStore:
    """Disk-backed cache for Gemini qualitative research, keyed by ticker."""

    def __init__(self, cache_dir: Path, ttl: int = GEMINI_DEFAULT_TTL) -> None:
        self.cache_dir = cache_dir
        self.ttl = ttl
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _data_path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker}.json"

    def _meta_path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker}.meta.json"

    def get(self, ticker: str) -> dict | None:
        """Return cached candidate data if present and not expired, else None."""
        meta_path = self._meta_path(ticker)
        data_path = self._data_path(ticker)

        if not meta_path.exists() or not data_path.exists():
            return None

        meta = json.loads(meta_path.read_text())
        age = time.time() - meta["timestamp"]
        if age > self.ttl:
            return None

        return json.loads(data_path.read_text())

    def put(self, ticker: str, data: dict) -> None:
        """Write candidate data and meta sidecar. Meta written first."""
        if not data:
            return

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "ticker": ticker,
            "timestamp": time.time(),
        }

        # Write ordering: meta first, then data (crash safety)
        self._meta_path(ticker).write_text(json.dumps(meta, indent=2))
        self._data_path(ticker).write_text(json.dumps(data, indent=2))

    def status(self) -> dict:
        """Report cache entries and expiry info."""
        if not self.cache_dir.exists():
            return {"count": 0, "ttl_seconds": self.ttl, "entries": []}

        data_files = [f for f in sorted(self.cache_dir.glob("*.json"))
                      if not f.name.endswith(".meta.json")]
        entries: list[dict] = []
        for data_file in data_files:
            ticker = data_file.stem
            meta_path = self._meta_path(ticker)
            expires_at = None
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                expires_at = meta["timestamp"] + self.ttl
            entries.append({"ticker": ticker, "expires_at": expires_at})

        return {
            "count": len(data_files),
            "ttl_seconds": self.ttl,
            "entries": entries,
        }

    def clear(self) -> None:
        """Remove all cached files and recreate empty cache_dir."""
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


def cached_transport(
    inner_transport: FmpTransport,
    cache_store: FmpCacheStore,
    *,
    fresh: bool = False,
) -> FmpTransport:
    """Wrap an FmpTransport with caching. Returns a new FmpTransport callable.

    The returned callable has a ``stats`` attribute (dict) tracking
    ``"hits"`` and ``"misses"`` counts, and a ``reset_stats()`` method.
    """

    stats: dict[str, int] = {"hits": 0, "misses": 0}

    def _transport(endpoint: str, params: dict[str, str]) -> list[dict] | dict:
        ticker = params.get("symbol", "UNKNOWN")

        if not fresh:
            cached = cache_store.get(endpoint, ticker)
            if cached is not None:
                stats["hits"] += 1
                return cached

        stats["misses"] += 1
        data = inner_transport(endpoint, params)
        cache_store.put(endpoint, ticker, data)
        return data

    _transport.stats = stats  # type: ignore[attr-defined]

    def _reset_stats() -> None:
        stats["hits"] = 0
        stats["misses"] = 0

    _transport.reset_stats = _reset_stats  # type: ignore[attr-defined]

    return _transport
