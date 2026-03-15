"""Tests for _build_peer_context helper in scanner module."""
import unittest
from unittest.mock import MagicMock

from edenfintech_scanner_bootstrap.scanner import _build_peer_context


class TestBuildPeerContext(unittest.TestCase):
    """Unit tests for _build_peer_context()."""

    def _make_fmp_client(
        self,
        *,
        peers: list[str] | None = None,
        profile_sector: str = "Healthcare",
        screener_results: list[dict] | None = None,
        quote_mkt_cap: float = 1_000_000_000,
        peer_metrics_result: list[dict] | None = None,
    ) -> MagicMock:
        """Build a mock FmpClient with configurable responses."""
        client = MagicMock()
        if peers is not None:
            client.stock_peers.return_value = peers
        else:
            client.stock_peers.side_effect = Exception("no peers")
        client.profile.return_value = {"sector": profile_sector}
        client.stock_screener.return_value = screener_results or []
        client.quote.return_value = {"marketCap": quote_mkt_cap}
        client.peer_metrics.return_value = peer_metrics_result or []
        return client

    def test_happy_path_returns_peer_metrics(self):
        """Primary path: stock_peers returns >=2 peers, peer_metrics called."""
        metrics = [
            {"ticker": "MCK", "latest_revenue_b": 250.0},
            {"ticker": "CAH", "latest_revenue_b": 180.0},
        ]
        client = self._make_fmp_client(
            peers=["MCK", "CAH", "COR"],
            peer_metrics_result=metrics,
        )
        result = _build_peer_context("OMI", client)
        self.assertEqual(result, metrics)
        client.peer_metrics.assert_called_once()
        call_kwargs = client.peer_metrics.call_args
        self.assertEqual(call_kwargs[1]["target_mkt_cap"], 1_000_000_000)

    def test_fallback_to_screener_when_few_peers(self):
        """Fallback: <2 peers from stock_peers, screener supplements."""
        client = self._make_fmp_client(
            peers=["MCK"],
            screener_results=[
                {"symbol": "CAH"},
                {"symbol": "COR"},
                {"symbol": "OMI"},  # target ticker, should be excluded
            ],
            peer_metrics_result=[{"ticker": "MCK"}, {"ticker": "CAH"}, {"ticker": "COR"}],
        )
        result = _build_peer_context("OMI", client)
        self.assertIsNotNone(result)
        client.stock_screener.assert_called_once()
        peer_tickers_arg = client.peer_metrics.call_args[0][0]
        self.assertNotIn("OMI", peer_tickers_arg)

    def test_fallback_when_stock_peers_raises(self):
        """stock_peers endpoint fails entirely, falls back to screener."""
        client = self._make_fmp_client(
            peers=None,  # triggers side_effect=Exception
            screener_results=[{"symbol": "MCK"}, {"symbol": "CAH"}],
            peer_metrics_result=[{"ticker": "MCK"}],
        )
        result = _build_peer_context("OMI", client)
        self.assertIsNotNone(result)
        client.stock_screener.assert_called_once()

    def test_no_peers_returns_none(self):
        """No peers from either source returns None."""
        client = self._make_fmp_client(
            peers=None,
            screener_results=[],
        )
        result = _build_peer_context("OMI", client)
        self.assertIsNone(result)
        client.peer_metrics.assert_not_called()

    def test_caps_at_five_peers(self):
        """Peer list capped at 5 regardless of source."""
        client = self._make_fmp_client(
            peers=["A", "B", "C", "D", "E", "F", "G"],
            peer_metrics_result=[],
        )
        _build_peer_context("OMI", client)
        peer_tickers_arg = client.peer_metrics.call_args[0][0]
        self.assertLessEqual(len(peer_tickers_arg), 5)

    def test_total_failure_returns_none(self):
        """If everything raises, returns None gracefully."""
        client = MagicMock()
        client.stock_peers.side_effect = Exception("fail")
        client.profile.side_effect = Exception("fail")
        result = _build_peer_context("OMI", client)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
