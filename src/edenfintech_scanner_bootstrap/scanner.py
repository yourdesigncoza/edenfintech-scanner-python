"""Scanner module: auto_scan and sector_scan orchestrators.

Provides end-to-end scanning of individual tickers (auto_scan) or
entire sectors (sector_scan) with integrated hardening gates.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .automation import AutoAnalyzeResult, auto_analyze
from .config import AppConfig
from .fmp import FmpClient, build_raw_candidate_from_fmp
from .hardening import (
    ExceptionPanelResult,
    cagr_exception_panel,
    detect_probability_anchoring,
    score_evidence_quality,
)
from .pipeline import ScanArtifacts, run_scan
from .reporting import render_scan_markdown
from .sector import check_sector_freshness

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TickerResult:
    """Result for a single ticker within a scan."""
    ticker: str
    status: str  # "PASS" | "FAIL" | "ERROR" | "PENDING_REVIEW"
    report_json_path: Path | None = None
    report_markdown_path: Path | None = None
    error: str | None = None
    hardening_flags: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ScanResult:
    """Aggregate result of a scan operation."""
    scan_id: str
    scan_type: str  # "auto-scan" | "sector-scan"
    sector: str | None
    tickers_processed: list[str]
    results: dict[str, TickerResult]
    manifest_path: Path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_scan_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _extract_hardening_flags(
    overlay_candidate: dict,
    raw_candidate: dict,
    *,
    config: AppConfig | None = None,
    analyst_transport=None,
    validator_transport=None,
    epistemic_transport=None,
) -> tuple[dict, str | None]:
    """Run hardening gates and return (flags_dict, status_override_or_none)."""
    flags: dict = {}
    status_override: str | None = None

    # 1. Probability anchoring detection
    analysis = overlay_candidate.get("analysis_inputs", {})
    prob = analysis.get("probability", {})
    base_prob = prob.get("base_probability_pct", 0.0)
    risk_type = analysis.get("dominant_risk_type", "")
    anchoring = detect_probability_anchoring(base_prob, risk_type)
    flags["anchoring"] = anchoring

    # 2. Evidence quality scoring
    evidence = score_evidence_quality(overlay_candidate)
    flags["evidence_quality"] = evidence

    # 3. CAGR exception panel (20-29.9%)
    base_assumptions = analysis.get("base_case_assumptions", {})
    cagr = base_assumptions.get("cagr_pct", 0.0)
    if 20.0 <= cagr < 30.0:
        try:
            panel_result = cagr_exception_panel(
                overlay_candidate,
                raw_candidate,
                analyst_transport=analyst_transport,
                validator_transport=validator_transport,
                epistemic_transport=epistemic_transport,
                config=config,
            )
            flags["cagr_exception"] = {
                "approved": panel_result.approved,
                "unanimous": panel_result.unanimous,
                "votes": [
                    {"agent": v.agent, "approve": v.approve, "reasoning": v.reasoning}
                    for v in panel_result.votes
                ],
            }
            if not panel_result.approved:
                status_override = "PENDING_REVIEW"
        except Exception as exc:
            logger.warning("CAGR exception panel failed for %s: %s", overlay_candidate.get("ticker"), exc)
            flags["cagr_exception"] = {"error": str(exc)}
            status_override = "PENDING_REVIEW"
    else:
        flags["cagr_exception"] = None

    return flags, status_override


def _process_single_ticker(
    ticker: str,
    auto_result: AutoAnalyzeResult,
    *,
    config: AppConfig,
    out_dir: Path,
    judge_transport=None,
    analyst_transport=None,
    validator_transport=None,
    epistemic_transport=None,
) -> TickerResult:
    """Process a single ticker: hardening gates, pipeline, write reports."""
    overlay = auto_result.finalized_overlay
    overlay_candidate = overlay.get("structured_candidates", [{}])[0]
    raw_candidate = auto_result.raw_bundle.get("raw_candidates", [{}])[0]

    # Run hardening gates
    flags, status_override = _extract_hardening_flags(
        overlay_candidate, raw_candidate,
        config=config,
        analyst_transport=analyst_transport,
        validator_transport=validator_transport,
        epistemic_transport=epistemic_transport,
    )

    # Build scan-input payload
    from .structured_analysis import apply_structured_analysis
    try:
        scan_payload = apply_structured_analysis(auto_result.raw_bundle, overlay)
    except Exception as exc:
        logger.warning("apply_structured_analysis failed for %s, building inline payload", ticker)
        # Build a minimal scan-input inline from overlay + raw bundle
        scan_payload = _build_inline_scan_payload(overlay_candidate, raw_candidate, auto_result.raw_bundle)

    # Run pipeline
    artifacts = run_scan(scan_payload, judge_config=config, judge_transport=judge_transport)

    # Write reports
    ticker_dir = out_dir / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)
    json_path = ticker_dir / "report.json"
    md_path = ticker_dir / "report.md"
    json_path.write_text(json.dumps(artifacts.report_json, indent=2))
    md_path.write_text(artifacts.report_markdown)

    # Determine status
    ranked = artifacts.report_json.get("ranked_candidates", [])
    status = "PASS" if ranked else "FAIL"
    if status_override:
        status = status_override

    return TickerResult(
        ticker=ticker,
        status=status,
        report_json_path=json_path,
        report_markdown_path=md_path,
        hardening_flags=flags,
    )


def _build_inline_scan_payload(overlay_candidate: dict, raw_candidate: dict, raw_bundle: dict) -> dict:
    """Build a minimal scan-input payload when apply_structured_analysis fails."""
    from datetime import date

    screening = overlay_candidate.get("screening_inputs", {})
    analysis = overlay_candidate.get("analysis_inputs", {})
    epistemic = overlay_candidate.get("epistemic_inputs", {})
    ticker = overlay_candidate.get("ticker", raw_candidate.get("ticker", "UNKNOWN"))

    candidate = {
        "ticker": ticker,
        "cluster_name": raw_candidate.get("cluster_name", f"{ticker.lower()}-cluster"),
        "industry": raw_candidate.get("industry", "Unknown Industry"),
        "current_price": raw_candidate.get("current_price", 0.0),
        "screening": {
            "pct_off_ath": screening.get("pct_off_ath", raw_candidate.get("market_snapshot", {}).get("pct_off_ath", 0.0)),
            "industry_understandable": screening.get("industry_understandable", True),
            "industry_in_secular_decline": screening.get("industry_in_secular_decline", False),
            "double_plus_potential": screening.get("double_plus_potential", True),
            "checks": screening.get("checks", {}),
        },
        "analysis": {
            **{k: v for k, v in analysis.items() if k not in ("base_case_assumptions",)},
        },
        "epistemic_review": epistemic,
    }

    return {
        "title": f"Auto-scan: {ticker}",
        "scan_date": raw_bundle.get("scan_date", str(date.today())),
        "version": "v1",
        "scan_parameters": raw_bundle.get("scan_parameters", {
            "scan_mode": "specific_tickers",
            "focus": ticker,
        }),
        "portfolio_context": raw_bundle.get("portfolio_context", {
            "current_positions": 0,
            "max_positions": 12,
        }),
        "methodology_notes": [],
        "candidates": [candidate],
    }


def _write_manifest(
    scan_result: ScanResult,
    *,
    started_at: str,
    clusters: dict[str, list[str]] | None = None,
) -> None:
    """Write manifest.json for a scan."""
    completed_at = datetime.now(timezone.utc).isoformat()

    tickers_data: dict = {}
    pass_count = 0
    fail_count = 0
    error_count = 0
    pending_count = 0

    for ticker, tr in scan_result.results.items():
        tickers_data[ticker] = {
            "status": tr.status,
            "report_json": str(tr.report_json_path) if tr.report_json_path else None,
            "report_markdown": str(tr.report_markdown_path) if tr.report_markdown_path else None,
            "error": tr.error,
            "hardening_flags": tr.hardening_flags,
        }
        if tr.status == "PASS":
            pass_count += 1
        elif tr.status == "FAIL":
            fail_count += 1
        elif tr.status == "ERROR":
            error_count += 1
        elif tr.status == "PENDING_REVIEW":
            pending_count += 1

    manifest: dict = {
        "scan_id": scan_result.scan_id,
        "scan_type": scan_result.scan_type,
        "sector": scan_result.sector,
        "started_at": started_at,
        "completed_at": completed_at,
        "tickers": tickers_data,
        "summary": {
            "total": len(scan_result.tickers_processed),
            "pass": pass_count,
            "fail": fail_count,
            "error": error_count,
            "pending_review": pending_count,
        },
    }

    if clusters is not None:
        manifest["clusters"] = clusters

    scan_result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    scan_result.manifest_path.write_text(json.dumps(manifest, indent=2))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def auto_scan(
    tickers: list[str],
    *,
    config: AppConfig,
    out_dir: Path | None = None,
    judge_transport=None,
    analyst_transport=None,
    validator_transport=None,
    epistemic_transport=None,
    analyst_client=None,
    validator_client=None,
    epistemic_client=None,
) -> ScanResult:
    """Run auto_analyze + pipeline for each ticker sequentially.

    Writes JSON and markdown reports per ticker and a manifest.json.
    """
    scan_id = _generate_scan_id()
    if out_dir is None:
        out_dir = Path("data") / "scans" / scan_id
    out_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()
    results: dict[str, TickerResult] = {}

    for ticker in tickers:
        try:
            auto_result = auto_analyze(
                ticker,
                config=config,
                out_dir=out_dir / ticker / "raw",
                analyst_client=analyst_client,
                validator_client=validator_client,
                epistemic_client=epistemic_client,
            )
            ticker_result = _process_single_ticker(
                ticker, auto_result,
                config=config,
                out_dir=out_dir,
                judge_transport=judge_transport,
                analyst_transport=analyst_transport,
                validator_transport=validator_transport,
                epistemic_transport=epistemic_transport,
            )
            results[ticker] = ticker_result
        except Exception as exc:
            logger.error("auto_scan error for %s: %s", ticker, exc)
            results[ticker] = TickerResult(
                ticker=ticker,
                status="ERROR",
                error=str(exc),
            )

    manifest_path = out_dir / "manifest.json"
    scan_result = ScanResult(
        scan_id=scan_id,
        scan_type="auto-scan",
        sector=None,
        tickers_processed=list(tickers),
        results=results,
        manifest_path=manifest_path,
    )
    _write_manifest(scan_result, started_at=started_at)
    return scan_result


def sector_scan(
    sector_name: str,
    *,
    config: AppConfig,
    out_dir: Path | None = None,
    max_workers: int = 3,
    excluded_industries: list[str] | None = None,
    fmp_client: FmpClient | None = None,
    judge_transport=None,
    analyst_transport=None,
    validator_transport=None,
    epistemic_transport=None,
    analyst_client=None,
    validator_client=None,
    epistemic_client=None,
) -> ScanResult:
    """Scan an entire sector: screener, filter, cluster, analyze.

    1. Check hydration via check_sector_freshness
    2. Get screener results via FMP
    3. Apply broken-chart filter (>= 60% off ATH)
    4. Exclude tickers in excluded_industries
    5. Cluster survivors by industry
    6. Run auto_analyze per ticker (ThreadPoolExecutor)
    7. Write manifest with clusters
    """
    scan_id = _generate_scan_id()
    if out_dir is None:
        out_dir = Path("data") / "scans" / scan_id
    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()

    # Step 1: Check hydration
    freshness = check_sector_freshness(sector_name)
    if freshness["status"] == "NOT_HYDRATED":
        raise ValueError(
            f"Sector '{sector_name}' is not hydrated. Run hydrate-sector first."
        )

    # Step 2: Get screener results
    if fmp_client is None:
        config.require("fmp_api_key")
        fmp_client = FmpClient(config.fmp_api_key)
    screener_results = fmp_client.stock_screener(sector_name)

    # Step 3: Broken-chart filter (>= 60% off ATH)
    survivors: list[dict] = []
    for item in screener_results:
        symbol = item.get("symbol", "")
        try:
            raw = build_raw_candidate_from_fmp(symbol, fmp_client)
            pct_off = raw.get("market_snapshot", {}).get("pct_off_ath", 0.0)
            if pct_off >= 60.0:
                item["_raw_candidate"] = raw
                item["_pct_off_ath"] = pct_off
                survivors.append(item)
            else:
                logger.info("Filtered %s: only %.1f%% off ATH", symbol, pct_off)
        except Exception as exc:
            logger.warning("Could not compute pct_off_ath for %s: %s", symbol, exc)

    # Step 4: Exclude industries
    excluded = set(excluded_industries or [])
    if excluded:
        survivors = [s for s in survivors if s.get("industry", "") not in excluded]

    # Step 5: Cluster by industry
    clusters: dict[str, list[str]] = defaultdict(list)
    for item in survivors:
        industry = item.get("industry", "Unknown")
        clusters[industry].append(item.get("symbol", ""))

    # Step 6: Run auto_analyze per ticker
    results: dict[str, TickerResult] = {}
    ticker_list = [item.get("symbol", "") for item in survivors]

    def _analyze_ticker(ticker: str) -> tuple[str, TickerResult]:
        try:
            auto_result = auto_analyze(
                ticker,
                config=config,
                out_dir=out_dir / ticker / "raw",
                analyst_client=analyst_client,
                validator_client=validator_client,
                epistemic_client=epistemic_client,
            )
            ticker_result = _process_single_ticker(
                ticker, auto_result,
                config=config,
                out_dir=out_dir,
                judge_transport=judge_transport,
                analyst_transport=analyst_transport,
                validator_transport=validator_transport,
                epistemic_transport=epistemic_transport,
            )
            return ticker, ticker_result
        except Exception as exc:
            logger.error("sector_scan error for %s: %s", ticker, exc)
            return ticker, TickerResult(ticker=ticker, status="ERROR", error=str(exc))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_analyze_ticker, t): t for t in ticker_list}
        for future in as_completed(futures):
            ticker, ticker_result = future.result()
            results[ticker] = ticker_result

    manifest_path = out_dir / "manifest.json"
    scan_result = ScanResult(
        scan_id=scan_id,
        scan_type="sector-scan",
        sector=sector_name,
        tickers_processed=ticker_list,
        results=results,
        manifest_path=manifest_path,
    )
    _write_manifest(scan_result, started_at=started_at, clusters=dict(clusters))
    return scan_result
