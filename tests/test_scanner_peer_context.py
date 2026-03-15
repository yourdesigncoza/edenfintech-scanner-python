"""Tests for _build_peer_context helper and sector_scan peer_context wiring."""
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from edenfintech_scanner_bootstrap.scanner import _build_peer_context, TickerResult


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


class TestSectorScanPeerContext(unittest.TestCase):
    """Verify sector_scan passes peer_context to auto_analyze."""

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.build_raw_candidate_from_fmp")
    @patch("edenfintech_scanner_bootstrap.scanner._build_peer_context")
    @patch("edenfintech_scanner_bootstrap.scanner.ensure_sector_knowledge")
    def test_sector_scan_passes_peer_context(
        self, mock_ensure, mock_build_peer, mock_build_raw, mock_auto_analyze
    ):
        """sector_scan must pass peer_context from _build_peer_context to auto_analyze."""
        fake_peers = [{"ticker": "MCK", "latest_revenue_b": 250.0}]
        mock_build_peer.return_value = fake_peers
        mock_build_raw.return_value = {
            "market_snapshot": {"pct_off_ath": 75.0, "current_price": 10.0, "all_time_high": 40.0},
        }
        mock_auto_analyze.return_value = MagicMock(
            ticker="OMI",
            status="completed",
            analysis={"screening": {"passed": True}},
            raw_bundle={},
            structured_analysis={},
        )

        # Mock FmpClient
        mock_fmp = MagicMock()
        mock_fmp.stock_screener.return_value = [{"symbol": "OMI", "industry": "Medical - Distribution"}]

        config = MagicMock()
        config.fmp_api_key = "test-key"

        from edenfintech_scanner_bootstrap.scanner import sector_scan
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("edenfintech_scanner_bootstrap.scanner._process_single_ticker") as mock_process:
                mock_process.return_value = TickerResult(
                    ticker="OMI", status="PASS",
                    report_json_path=None, report_markdown_path=None,
                )
                sector_scan(
                    "Healthcare",
                    config=config,
                    out_dir=Path(tmpdir),
                    fmp_client=mock_fmp,
                    max_workers=1,
                )

        # Assert _build_peer_context was called for each ticker
        mock_build_peer.assert_called_once_with("OMI", mock_fmp)
        # Assert auto_analyze received peer_context
        auto_call_kwargs = mock_auto_analyze.call_args[1]
        self.assertEqual(auto_call_kwargs["peer_context"], fake_peers)


if __name__ == "__main__":
    unittest.main()
