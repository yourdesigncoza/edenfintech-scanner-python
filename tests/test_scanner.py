"""Tests for scanner module: auto_scan, sector_scan, and CLI dispatch."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from edenfintech_scanner_bootstrap.config import AppConfig
from edenfintech_scanner_bootstrap.fmp import FmpClient
from edenfintech_scanner_bootstrap.hardening import ExceptionPanelResult, ExceptionVote


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> AppConfig:
    defaults = {
        "fmp_api_key": "test-fmp-key",
        "gemini_api_key": "test-gemini-key",
        "openai_api_key": None,
        "codex_judge_model": "test-model",
        "anthropic_api_key": "test-anthropic-key",
    }
    defaults.update(overrides)
    return AppConfig(**defaults)


def _make_auto_analyze_result(ticker: str, *, cagr_pct: float = 35.0, base_prob: float = 70.0, risk_type: str = "Operational/Financial"):
    """Build a minimal AutoAnalyzeResult-like object."""
    from edenfintech_scanner_bootstrap.automation import AutoAnalyzeResult

    overlay = {
        "ticker": ticker,
        "completion_status": "FINALIZED",
        "finalization_metadata": {"reviewer": "test", "final_status": "LLM_CONFIRMED"},
        "source_bundle": {"scan_date": "2026-01-01"},
        "structured_candidates": [{
            "ticker": ticker,
            "provenance": [
                {"field_path": "test", "review_note": "SEC filing confirms revenue growth"},
            ],
            "screening_inputs": {
                "pct_off_ath": 72.0,
                "industry_understandable": True,
                "industry_in_secular_decline": False,
                "double_plus_potential": True,
                "checks": {
                    "solvency": {"verdict": "PASS", "note": "OK"},
                    "dilution": {"verdict": "PASS", "note": "OK"},
                    "revenue_growth": {"verdict": "PASS", "note": "OK"},
                    "roic": {"verdict": "PASS", "note": "OK"},
                    "valuation": {"verdict": "PASS", "note": "OK"},
                },
            },
            "analysis_inputs": {
                "thesis_summary": "Test thesis",
                "catalysts": ["Catalyst A"],
                "key_risks": ["Risk A"],
                "catalyst_stack": [{"type": "HARD", "description": "Test", "timeline": "Q1"}],
                "invalidation_triggers": [{"trigger": "Test", "evidence": "Test"}],
                "decision_memo": {"better_than_peer": "A", "safer_than_peer": "B", "what_makes_wrong": "C"},
                "issues_and_fixes": [{"issue": "A", "fix": "B", "evidence_status": "ACTION_UNDERWAY"}],
                "setup_pattern": "QUALITY_FRANCHISE",
                "moat_assessment": "Good moat",
                "margin_trend_gate": "PASS",
                "final_cluster_status": "CLEAR_WINNER",
                "catalyst_classification": "VALID_CATALYST",
                "dominant_risk_type": risk_type,
                "base_case_assumptions": {"cagr_pct": cagr_pct},
                "base_case": {"revenue_b": 3.0, "fcf_margin_pct": 10.0, "multiple": 24.0, "shares_m": 120.0, "years": 3.0},
                "worst_case": {"revenue_b": 2.4, "fcf_margin_pct": 8.0, "multiple": 12.0, "shares_m": 120.0},
                "probability": {"base_probability_pct": base_prob, "base_rate": "test", "likert_adjustments": "test"},
                "exception_20_pct_gate": {"eligible": False},
                "stretch_case": {"revenue_b": 3.5, "fcf_margin_pct": 12.0, "multiple": 28.0, "shares_m": 120.0, "years": 3.0},
            },
            "epistemic_inputs": {
                "q1_operational": {"answer": "Yes", "justification": "Test", "evidence": "Test"},
                "q2_regulatory": {"answer": "Yes", "justification": "Test", "evidence": "Test"},
                "q3_precedent": {"answer": "Yes", "justification": "Test", "evidence": "Test"},
                "q4_nonbinary": {"answer": "Yes", "justification": "Test", "evidence": "Test"},
                "q5_macro": {"answer": "Yes", "justification": "Test", "evidence": "Test"},
            },
        }],
    }

    raw_bundle = {
        "scan_date": "2026-01-01",
        "scan_parameters": {"scan_mode": "specific_tickers", "focus": ticker},
        "raw_candidates": [{
            "ticker": ticker,
            "cluster_name": f"{ticker.lower()}-cluster",
            "industry": "Test Industry",
            "current_price": 25.0,
            "market_snapshot": {"current_price": 25.0, "all_time_high": 100.0, "pct_off_ath": 75.0},
        }],
    }

    return AutoAnalyzeResult(
        ticker=ticker,
        finalized_overlay=overlay,
        validator_verdict={"verdict": "APPROVE"},
        epistemic_result={"overall": "PASS"},
        retries_used=0,
        raw_bundle=raw_bundle,
    )


def _make_scan_artifacts():
    """Build a minimal ScanArtifacts-like return value."""
    from edenfintech_scanner_bootstrap.pipeline import ScanArtifacts
    return ScanArtifacts(
        report_json={"title": "Test", "ranked_candidates": [{"ticker": "AAPL", "rank": 1}]},
        report_markdown="# Test Report",
        execution_log={"entries": [], "candidate_count": 1, "survivor_count": 1},
        judge={"verdict": "PASS"},
    )


# ---------------------------------------------------------------------------
# Test FMP stock_screener
# ---------------------------------------------------------------------------

class TestFmpStockScreener(unittest.TestCase):
    def test_stock_screener_calls_get_correctly(self):
        transport = MagicMock(return_value=[{"symbol": "KO", "industry": "Beverages"}])
        client = FmpClient("test-key", transport=transport)
        result = client.stock_screener("Consumer Defensive", exchange="NYSE")
        self.assertEqual(result, [{"symbol": "KO", "industry": "Beverages"}])
        transport.assert_called_once()
        call_args = transport.call_args
        self.assertEqual(call_args[0][0], "stock-screener")
        self.assertIn("sector", call_args[0][1])
        self.assertEqual(call_args[0][1]["sector"], "Consumer Defensive")
        self.assertEqual(call_args[0][1]["exchange"], "NYSE")

    def test_stock_screener_malformed_response(self):
        transport = MagicMock(return_value={"error": "bad"})
        client = FmpClient("test-key", transport=transport)
        with self.assertRaises(RuntimeError):
            client.stock_screener("Consumer Defensive")

    def test_stock_screener_extra_filters(self):
        transport = MagicMock(return_value=[])
        client = FmpClient("test-key", transport=transport)
        client.stock_screener("Technology", exchange="NASDAQ", marketCapMoreThan="1000000000")
        call_args = transport.call_args
        self.assertIn("marketCapMoreThan", call_args[0][1])


# ---------------------------------------------------------------------------
# Test auto_scan
# ---------------------------------------------------------------------------

class TestAutoScan(unittest.TestCase):
    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    def test_auto_scan_two_tickers(self, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import auto_scan

        mock_auto_analyze.side_effect = [
            _make_auto_analyze_result("AAPL"),
            _make_auto_analyze_result("MSFT"),
        ]
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test"
        mock_anchoring.return_value = None
        mock_evidence.return_value = {"total_citations": 1, "concrete_count": 1, "vague_count": 0, "concrete_ratio": 1.0, "methodology_warning": None}

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = auto_scan(["AAPL", "MSFT"], config=config, out_dir=Path(tmpdir))

            self.assertEqual(result.scan_type, "auto-scan")
            self.assertEqual(len(result.tickers_processed), 2)
            self.assertIn("AAPL", result.results)
            self.assertIn("MSFT", result.results)
            self.assertEqual(mock_auto_analyze.call_count, 2)
            # Manifest was written
            self.assertTrue(result.manifest_path.exists())

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    def test_auto_scan_manifest_structure(self, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import auto_scan

        mock_auto_analyze.return_value = _make_auto_analyze_result("AAPL")
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test"
        mock_anchoring.return_value = None
        mock_evidence.return_value = {"total_citations": 1, "concrete_count": 1, "vague_count": 0, "concrete_ratio": 1.0, "methodology_warning": None}

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = auto_scan(["AAPL"], config=config, out_dir=Path(tmpdir))
            manifest = json.loads(result.manifest_path.read_text())

            self.assertIn("scan_id", manifest)
            self.assertEqual(manifest["scan_type"], "auto-scan")
            self.assertIn("tickers", manifest)
            self.assertIn("AAPL", manifest["tickers"])
            self.assertIn("summary", manifest)
            self.assertIn("started_at", manifest)
            self.assertIn("completed_at", manifest)

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    def test_auto_scan_writes_reports(self, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import auto_scan

        mock_auto_analyze.return_value = _make_auto_analyze_result("AAPL")
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test Report"
        mock_anchoring.return_value = None
        mock_evidence.return_value = {"total_citations": 1, "concrete_count": 1, "vague_count": 0, "concrete_ratio": 1.0, "methodology_warning": None}

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = auto_scan(["AAPL"], config=config, out_dir=Path(tmpdir))
            ticker_result = result.results["AAPL"]

            self.assertIn(ticker_result.status, ("PASS", "FAIL", "ERROR"))
            self.assertIsNotNone(ticker_result.report_json_path)
            self.assertIsNotNone(ticker_result.report_markdown_path)
            self.assertTrue(ticker_result.report_json_path.exists())
            self.assertTrue(ticker_result.report_markdown_path.exists())

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    def test_auto_scan_anchoring_flag(self, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import auto_scan

        mock_auto_analyze.return_value = _make_auto_analyze_result("AAPL", base_prob=60.0, risk_type="Cyclical/Macro")
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test"
        mock_anchoring.return_value = {"flag": "PROBABILITY_ANCHORING_SUSPECT"}
        mock_evidence.return_value = {"total_citations": 1, "concrete_count": 1, "vague_count": 0, "concrete_ratio": 1.0, "methodology_warning": None}

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = auto_scan(["AAPL"], config=config, out_dir=Path(tmpdir))
            ticker_result = result.results["AAPL"]

            self.assertIn("anchoring", ticker_result.hardening_flags)
            self.assertIsNotNone(ticker_result.hardening_flags["anchoring"])

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    def test_auto_scan_evidence_quality_warning(self, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import auto_scan

        mock_auto_analyze.return_value = _make_auto_analyze_result("AAPL")
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test"
        mock_anchoring.return_value = None
        mock_evidence.return_value = {
            "total_citations": 5, "concrete_count": 1, "vague_count": 4,
            "concrete_ratio": 0.2, "methodology_warning": "Evidence quality below threshold",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = auto_scan(["AAPL"], config=config, out_dir=Path(tmpdir))
            ticker_result = result.results["AAPL"]

            self.assertIn("evidence_quality", ticker_result.hardening_flags)
            self.assertIsNotNone(ticker_result.hardening_flags["evidence_quality"].get("methodology_warning"))

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    @patch("edenfintech_scanner_bootstrap.scanner.cagr_exception_panel")
    def test_auto_scan_cagr_exception_approved(self, mock_cagr, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import auto_scan

        mock_auto_analyze.return_value = _make_auto_analyze_result("AAPL", cagr_pct=25.0)
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test"
        mock_anchoring.return_value = None
        mock_evidence.return_value = {"total_citations": 1, "concrete_count": 1, "vague_count": 0, "concrete_ratio": 1.0, "methodology_warning": None}
        mock_cagr.return_value = ExceptionPanelResult(
            votes=[
                ExceptionVote(agent="analyst", approve=True, reasoning="OK"),
                ExceptionVote(agent="validator", approve=True, reasoning="OK"),
                ExceptionVote(agent="epistemic", approve=True, reasoning="OK"),
            ],
            unanimous=True,
            approved=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = auto_scan(["AAPL"], config=config, out_dir=Path(tmpdir))
            ticker_result = result.results["AAPL"]
            self.assertEqual(ticker_result.status, "PASS")

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    @patch("edenfintech_scanner_bootstrap.scanner.cagr_exception_panel")
    def test_auto_scan_cagr_exception_rejected(self, mock_cagr, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import auto_scan

        mock_auto_analyze.return_value = _make_auto_analyze_result("AAPL", cagr_pct=25.0)
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test"
        mock_anchoring.return_value = None
        mock_evidence.return_value = {"total_citations": 1, "concrete_count": 1, "vague_count": 0, "concrete_ratio": 1.0, "methodology_warning": None}
        mock_cagr.return_value = ExceptionPanelResult(
            votes=[
                ExceptionVote(agent="analyst", approve=True, reasoning="OK"),
                ExceptionVote(agent="validator", approve=False, reasoning="No"),
                ExceptionVote(agent="epistemic", approve=True, reasoning="OK"),
            ],
            unanimous=False,
            approved=False,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = auto_scan(["AAPL"], config=config, out_dir=Path(tmpdir))
            ticker_result = result.results["AAPL"]
            self.assertEqual(ticker_result.status, "PENDING_REVIEW")

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    def test_auto_scan_error_handling(self, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import auto_scan

        mock_auto_analyze.side_effect = RuntimeError("API down")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = auto_scan(["AAPL"], config=config, out_dir=Path(tmpdir))
            ticker_result = result.results["AAPL"]
            self.assertEqual(ticker_result.status, "ERROR")
            self.assertIn("API down", ticker_result.error)


# ---------------------------------------------------------------------------
# Test sector_scan
# ---------------------------------------------------------------------------

class TestSectorScan(unittest.TestCase):
    @patch("edenfintech_scanner_bootstrap.scanner.check_sector_freshness")
    def test_sector_scan_not_hydrated(self, mock_freshness):
        from edenfintech_scanner_bootstrap.scanner import sector_scan

        mock_freshness.return_value = {"status": "NOT_HYDRATED"}
        config = _make_config()

        with self.assertRaises(ValueError):
            sector_scan("Consumer Defensive", config=config)

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    @patch("edenfintech_scanner_bootstrap.scanner.check_sector_freshness")
    @patch("edenfintech_scanner_bootstrap.scanner.build_raw_candidate_from_fmp")
    def test_sector_scan_broken_chart_filter(self, mock_build_raw, mock_freshness, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import sector_scan

        mock_freshness.return_value = {"status": "FRESH"}

        screener_results = [
            {"symbol": "KO", "industry": "Beverages"},
            {"symbol": "PEP", "industry": "Beverages"},
            {"symbol": "MDLZ", "industry": "Snacks"},
        ]
        fmp_client = MagicMock(spec=FmpClient)
        fmp_client.stock_screener.return_value = screener_results

        # KO: 70% off ATH (passes), PEP: 40% off ATH (filtered), MDLZ: 65% off (passes)
        mock_build_raw.side_effect = [
            {"ticker": "KO", "market_snapshot": {"pct_off_ath": 70.0}, "industry": "Beverages"},
            {"ticker": "PEP", "market_snapshot": {"pct_off_ath": 40.0}, "industry": "Beverages"},
            {"ticker": "MDLZ", "market_snapshot": {"pct_off_ath": 65.0}, "industry": "Snacks"},
        ]
        mock_auto_analyze.return_value = _make_auto_analyze_result("KO")
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test"
        mock_anchoring.return_value = None
        mock_evidence.return_value = {"total_citations": 1, "concrete_count": 1, "vague_count": 0, "concrete_ratio": 1.0, "methodology_warning": None}

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = sector_scan("Consumer Defensive", config=config, out_dir=Path(tmpdir), fmp_client=fmp_client)
            # PEP should be filtered out (only 40% off ATH)
            # auto_analyze called for KO and MDLZ only
            self.assertEqual(mock_auto_analyze.call_count, 2)

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    @patch("edenfintech_scanner_bootstrap.scanner.check_sector_freshness")
    @patch("edenfintech_scanner_bootstrap.scanner.build_raw_candidate_from_fmp")
    def test_sector_scan_exclude_industries(self, mock_build_raw, mock_freshness, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import sector_scan

        mock_freshness.return_value = {"status": "FRESH"}

        screener_results = [
            {"symbol": "KO", "industry": "Beverages"},
            {"symbol": "MO", "industry": "Tobacco"},
        ]
        fmp_client = MagicMock(spec=FmpClient)
        fmp_client.stock_screener.return_value = screener_results

        mock_build_raw.side_effect = [
            {"ticker": "KO", "market_snapshot": {"pct_off_ath": 70.0}, "industry": "Beverages"},
            {"ticker": "MO", "market_snapshot": {"pct_off_ath": 80.0}, "industry": "Tobacco"},
        ]
        mock_auto_analyze.return_value = _make_auto_analyze_result("KO")
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test"
        mock_anchoring.return_value = None
        mock_evidence.return_value = {"total_citations": 1, "concrete_count": 1, "vague_count": 0, "concrete_ratio": 1.0, "methodology_warning": None}

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = sector_scan(
                "Consumer Defensive", config=config, out_dir=Path(tmpdir),
                fmp_client=fmp_client, excluded_industries=["Tobacco"],
            )
            # MO excluded by industry
            self.assertEqual(mock_auto_analyze.call_count, 1)

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    @patch("edenfintech_scanner_bootstrap.scanner.check_sector_freshness")
    @patch("edenfintech_scanner_bootstrap.scanner.build_raw_candidate_from_fmp")
    def test_sector_scan_manifest_has_sector(self, mock_build_raw, mock_freshness, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import sector_scan

        mock_freshness.return_value = {"status": "FRESH"}
        fmp_client = MagicMock(spec=FmpClient)
        fmp_client.stock_screener.return_value = [{"symbol": "KO", "industry": "Beverages"}]
        mock_build_raw.return_value = {"ticker": "KO", "market_snapshot": {"pct_off_ath": 70.0}, "industry": "Beverages"}
        mock_auto_analyze.return_value = _make_auto_analyze_result("KO")
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test"
        mock_anchoring.return_value = None
        mock_evidence.return_value = {"total_citations": 1, "concrete_count": 1, "vague_count": 0, "concrete_ratio": 1.0, "methodology_warning": None}

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = sector_scan("Consumer Defensive", config=config, out_dir=Path(tmpdir), fmp_client=fmp_client)
            self.assertEqual(result.scan_type, "sector-scan")
            self.assertEqual(result.sector, "Consumer Defensive")

            manifest = json.loads(result.manifest_path.read_text())
            self.assertEqual(manifest["scan_type"], "sector-scan")
            self.assertEqual(manifest["sector"], "Consumer Defensive")

    @patch("edenfintech_scanner_bootstrap.scanner.auto_analyze")
    @patch("edenfintech_scanner_bootstrap.scanner.run_scan")
    @patch("edenfintech_scanner_bootstrap.scanner.render_scan_markdown")
    @patch("edenfintech_scanner_bootstrap.scanner.detect_probability_anchoring")
    @patch("edenfintech_scanner_bootstrap.scanner.score_evidence_quality")
    @patch("edenfintech_scanner_bootstrap.scanner.check_sector_freshness")
    @patch("edenfintech_scanner_bootstrap.scanner.build_raw_candidate_from_fmp")
    def test_sector_scan_clusters_by_industry(self, mock_build_raw, mock_freshness, mock_evidence, mock_anchoring, mock_render, mock_run_scan, mock_auto_analyze):
        from edenfintech_scanner_bootstrap.scanner import sector_scan

        mock_freshness.return_value = {"status": "FRESH"}
        fmp_client = MagicMock(spec=FmpClient)
        fmp_client.stock_screener.return_value = [
            {"symbol": "KO", "industry": "Beverages"},
            {"symbol": "PEP", "industry": "Beverages"},
            {"symbol": "MDLZ", "industry": "Snacks"},
        ]
        mock_build_raw.side_effect = [
            {"ticker": "KO", "market_snapshot": {"pct_off_ath": 70.0}, "industry": "Beverages"},
            {"ticker": "PEP", "market_snapshot": {"pct_off_ath": 75.0}, "industry": "Beverages"},
            {"ticker": "MDLZ", "market_snapshot": {"pct_off_ath": 65.0}, "industry": "Snacks"},
        ]
        mock_auto_analyze.return_value = _make_auto_analyze_result("KO")
        mock_run_scan.return_value = _make_scan_artifacts()
        mock_render.return_value = "# Test"
        mock_anchoring.return_value = None
        mock_evidence.return_value = {"total_citations": 1, "concrete_count": 1, "vague_count": 0, "concrete_ratio": 1.0, "methodology_warning": None}

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            result = sector_scan("Consumer Defensive", config=config, out_dir=Path(tmpdir), fmp_client=fmp_client, max_workers=1)

            manifest = json.loads(result.manifest_path.read_text())
            self.assertIn("clusters", manifest)
            cluster_names = set(manifest["clusters"].keys())
            self.assertIn("Beverages", cluster_names)
            self.assertIn("Snacks", cluster_names)


# ---------------------------------------------------------------------------
# Test CLI dispatch
# ---------------------------------------------------------------------------

class TestCliDispatch(unittest.TestCase):
    @patch("edenfintech_scanner_bootstrap.scanner.auto_scan")
    @patch("edenfintech_scanner_bootstrap.cli.load_config")
    def test_cmd_auto_scan(self, mock_config, mock_auto_scan):
        from edenfintech_scanner_bootstrap.cli import main
        from edenfintech_scanner_bootstrap.scanner import ScanResult

        mock_config.return_value = _make_config()
        mock_auto_scan.return_value = ScanResult(
            scan_id="test-id",
            scan_type="auto-scan",
            sector=None,
            tickers_processed=["AAPL"],
            results={},
            manifest_path=Path("/tmp/manifest.json"),
        )

        result = main(["auto-scan", "AAPL"])
        mock_auto_scan.assert_called_once()
        call_kwargs = mock_auto_scan.call_args
        self.assertIn("AAPL", call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("tickers", []))

    @patch("edenfintech_scanner_bootstrap.scanner.sector_scan")
    @patch("edenfintech_scanner_bootstrap.cli.load_config")
    def test_cmd_sector_scan(self, mock_config, mock_sector_scan):
        from edenfintech_scanner_bootstrap.cli import main
        from edenfintech_scanner_bootstrap.scanner import ScanResult

        mock_config.return_value = _make_config()
        mock_sector_scan.return_value = ScanResult(
            scan_id="test-id",
            scan_type="sector-scan",
            sector="Consumer Defensive",
            tickers_processed=["KO"],
            results={},
            manifest_path=Path("/tmp/manifest.json"),
        )

        result = main(["sector-scan", "Consumer Defensive"])
        mock_sector_scan.assert_called_once()
        call_args = mock_sector_scan.call_args
        self.assertEqual(call_args[0][0] if call_args[0] else call_args[1].get("sector_name"), "Consumer Defensive")


if __name__ == "__main__":
    unittest.main()
