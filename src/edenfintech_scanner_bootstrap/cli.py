from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assets import contract_path, gemini_raw_bundle_schema_path, holdings_schema_path, load_json, scan_input_schema_path, structured_analysis_schema_path
from .cache import FmpCacheStore, cached_transport
from .config import discover_project_root, load_config
from .analyst import ClaudeAnalystClient, generate_llm_analysis_draft
from .field_generation import build_structured_analysis_draft_file
from .fmp import FmpClient, build_fmp_bundle_with_config, write_fmp_bundle
from .holding_review import review_holding
from .gemini import GeminiClient, build_gemini_bundle_with_config, merge_fmp_and_gemini_bundles, write_gemini_bundle
from .importers import build_scan_input_file, load_raw_scan_template_text
from .judge import run_judge_file
from .live_scan import run_live_scan
from .pipeline import load_scan_input_template_text, run_scan_file, validate_scan_input_file
from .review_package import build_review_package
from .regression import run_regression_suite
from .structured_analysis import (
    build_structured_analysis_template_file,
    finalize_structured_analysis_file,
    review_structured_analysis_file,
    suggest_review_notes_file,
)
from .scanner import auto_scan, sector_scan
from .sector import check_sector_freshness, hydrate_sector, _load_registry, _slugify
from .validation import validate_assets


def _cmd_validate_assets() -> int:
    report = validate_assets()
    for message in report.messages:
        print(message)
    return 0 if report.ok else 1


def _cmd_run_regression() -> int:
    results = run_regression_suite()
    failed = False
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{result.fixture_id}: {status}")
        for detail in result.details:
            print(f"  - {detail}")
        failed = failed or not result.passed
    return 1 if failed else 0


def _cmd_show_contract(stage_id: str) -> int:
    contract = load_json(contract_path(stage_id))
    print(json.dumps(contract, indent=2))
    return 0


def _cmd_run_scan(
    input_path: str,
    json_out: str | None,
    markdown_out: str | None,
    execution_log_out: str | None,
) -> int:
    artifacts = run_scan_file(
        Path(input_path),
        json_out=Path(json_out) if json_out else None,
        markdown_out=Path(markdown_out) if markdown_out else None,
        execution_log_out=Path(execution_log_out) if execution_log_out else None,
    )
    print(json.dumps(artifacts.report_json, indent=2))
    return 0


def _cmd_show_scan_template() -> int:
    print(load_scan_input_template_text(), end="")
    return 0


def _cmd_validate_scan_input(input_path: str) -> int:
    validate_scan_input_file(Path(input_path))
    print("scan input validated")
    return 0


def _cmd_show_scan_schema() -> int:
    schema = load_json(scan_input_schema_path())
    print(json.dumps(schema, indent=2))
    return 0


def _cmd_show_gemini_schema() -> int:
    schema = load_json(gemini_raw_bundle_schema_path())
    print(json.dumps(schema, indent=2))
    return 0


def _cmd_show_structured_analysis_schema() -> int:
    schema = load_json(structured_analysis_schema_path())
    print(json.dumps(schema, indent=2))
    return 0


def _cmd_build_scan_input(raw_input_path: str, json_out: str | None) -> int:
    load_config()
    payload = build_scan_input_file(
        Path(raw_input_path),
        json_out=Path(json_out) if json_out else None,
    )
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_show_raw_scan_template() -> int:
    print(load_raw_scan_template_text(), end="")
    return 0


def _cmd_build_structured_analysis_template(raw_bundle_path: str, json_out: str | None) -> int:
    payload = build_structured_analysis_template_file(
        Path(raw_bundle_path),
        json_out=Path(json_out) if json_out else None,
    )
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_generate_structured_analysis_draft(raw_bundle_path: str, json_out: str | None) -> int:
    payload = build_structured_analysis_draft_file(
        Path(raw_bundle_path),
        json_out=Path(json_out) if json_out else None,
    )
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_generate_llm_analysis_draft(raw_bundle_path: str, json_out: str | None) -> int:
    config = load_config()
    config.require("anthropic_api_key")
    raw_bundle = load_json(Path(raw_bundle_path))
    client = ClaudeAnalystClient(
        config.anthropic_api_key,
        model=config.analyst_model,
    )
    payload = generate_llm_analysis_draft(raw_bundle, client=client)
    if json_out:
        out_path = Path(json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_finalize_structured_analysis(
    structured_analysis_path: str,
    reviewer: str,
    json_out: str | None,
    final_status: str,
    note: str | None,
) -> int:
    payload = finalize_structured_analysis_file(
        Path(structured_analysis_path),
        reviewer=reviewer,
        json_out=Path(json_out) if json_out else None,
        final_status=final_status,
        note=note,
    )
    print(json.dumps(payload, indent=2))
    return 0


def _parse_review_note_update(spec: str) -> dict[str, str]:
    if "=" not in spec:
        raise ValueError("review note update must use FIELD_PATH=NOTE or TICKER:FIELD_PATH=NOTE")
    target, note = spec.split("=", 1)
    ticker = None
    field_path = target
    if ":" in target:
        ticker, field_path = target.split(":", 1)
    return {
        "ticker": ticker or "",
        "field_path": field_path.strip(),
        "review_note": note.strip(),
    }


def _cmd_review_structured_analysis(
    structured_analysis_path: str,
    json_out: str | None,
    markdown_out: str | None,
    overlay_out: str | None,
    set_note: list[str] | None,
) -> int:
    updates = [_parse_review_note_update(spec) for spec in (set_note or [])]
    if updates and not overlay_out:
        raise ValueError("--overlay-out is required when --set-note is used")
    report = review_structured_analysis_file(
        Path(structured_analysis_path),
        json_out=Path(json_out) if json_out else None,
        markdown_out=Path(markdown_out) if markdown_out else None,
        overlay_out=Path(overlay_out) if overlay_out else None,
        note_updates=updates,
    )
    print(json.dumps(report, indent=2))
    return 0


def _cmd_suggest_review_notes(
    structured_analysis_path: str,
    json_out: str | None,
    markdown_out: str | None,
) -> int:
    report = suggest_review_notes_file(
        Path(structured_analysis_path),
        json_out=Path(json_out) if json_out else None,
        markdown_out=Path(markdown_out) if markdown_out else None,
    )
    print(json.dumps(report, indent=2))
    return 0


def _cmd_run_judge(report_path: str, execution_log_path: str) -> int:
    load_config()
    result = run_judge_file(Path(report_path), Path(execution_log_path))
    print(json.dumps(result, indent=2))
    return 0


def _default_fmp_cache_dir() -> Path:
    root = discover_project_root()
    if root is None:
        root = Path.cwd()
    return root / "data" / "cache" / "fmp"


def _cmd_fetch_fmp_bundle(tickers: list[str], json_out: str | None, fresh: bool = False) -> int:
    config = load_config()
    from .fmp import _default_transport
    store = FmpCacheStore(_default_fmp_cache_dir())
    transport = cached_transport(_default_transport, store, fresh=fresh)
    bundle = build_fmp_bundle_with_config(tickers, config=config, transport=transport)
    if json_out:
        write_fmp_bundle(Path(json_out), bundle)
    print(json.dumps(bundle, indent=2))
    return 0


def _cmd_cache_status(cache_dir: Path | None = None) -> int:
    store = FmpCacheStore(cache_dir or _default_fmp_cache_dir())
    status = store.status()
    if not status:
        print("Cache is empty.")
        return 0
    for endpoint, info in sorted(status.items()):
        print(f"{endpoint}: {info['count']} entries (TTL: {info['ttl_seconds']}s)")
        for entry in info["entries"]:
            expires = entry.get("expires_at")
            label = f"  expires_at={expires:.0f}" if expires else "  no meta"
            print(f"  {entry['ticker']}{label}")
    return 0


def _cmd_cache_clear(cache_dir: Path | None = None) -> int:
    store = FmpCacheStore(cache_dir or _default_fmp_cache_dir())
    store.clear()
    print("Cache cleared.")
    return 0


def _cmd_fetch_gemini_bundle(
    tickers: list[str],
    json_out: str | None,
    focus: str | None,
    research_question: str | None,
    model: str | None,
) -> int:
    config = load_config()
    bundle = build_gemini_bundle_with_config(
        tickers,
        config=config,
        focus=focus,
        research_question=research_question,
        model=model or "gemini-3-pro-preview",
    )
    if json_out:
        write_gemini_bundle(Path(json_out), bundle)
    print(json.dumps(bundle, indent=2))
    return 0


def _cmd_merge_raw_bundles(fmp_bundle_path: str, gemini_bundle_path: str, json_out: str | None) -> int:
    merged = merge_fmp_and_gemini_bundles(
        load_json(Path(fmp_bundle_path)),
        load_json(Path(gemini_bundle_path)),
    )
    if json_out:
        write_fmp_bundle(Path(json_out), merged)
    print(json.dumps(merged, indent=2))
    return 0


def _cmd_run_live_scan(
    tickers: list[str],
    out_dir: str,
    stop_at: str,
    structured_analysis_path: str | None,
    focus: str | None,
    research_question: str | None,
    gemini_model: str | None,
    fresh: bool = False,
) -> int:
    config = load_config()
    from .fmp import _default_transport
    store = FmpCacheStore(_default_fmp_cache_dir())
    fmp_transport = cached_transport(_default_transport, store, fresh=fresh)
    result = run_live_scan(
        tickers,
        out_dir=Path(out_dir),
        stop_at=stop_at,
        structured_analysis_path=Path(structured_analysis_path) if structured_analysis_path else None,
        config=config,
        fmp_transport=fmp_transport,
        focus=focus,
        research_question=research_question,
        gemini_model=gemini_model or "gemini-3-pro-preview",
    )
    print(
        json.dumps(
            {
                "stop_at": result.stop_at,
                "out_dir": str(result.out_dir),
                "written_paths": {key: str(path) for key, path in result.written_paths.items()},
            },
            indent=2,
        )
    )
    return 0


def _cmd_hydrate_sector(sector_name: str, sub_sectors: list[str] | None, model: str | None) -> int:
    config = load_config()
    config.require("gemini_api_key")
    kwargs: dict = {}
    if model:
        kwargs["model"] = model
    client = GeminiClient(config.gemini_api_key, **kwargs)
    try:
        result = hydrate_sector(
            sector_name,
            sub_sectors=sub_sectors,
            client=client,
            config=config,
        )
    except (ValueError, Exception) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    slug = _slugify(sector_name)
    root = discover_project_root() or Path.cwd()
    knowledge_path = root / "data" / "sectors" / slug / "knowledge.json"
    print(f"Hydrated sector '{sector_name}' -> {knowledge_path}")
    return 0


def _cmd_sector_status(sector_name_filter: str | None) -> int:
    root = discover_project_root() or Path.cwd()
    registry = _load_registry(root)
    sectors = registry.get("sectors", {})

    if sector_name_filter:
        slug = _slugify(sector_name_filter)
        if slug in sectors:
            sectors = {slug: sectors[slug]}
        else:
            # Check freshness which handles NOT_HYDRATED
            result = check_sector_freshness(sector_name_filter, project_root=root)
            print(f"{'Sector':<30} {'Hydrated':<25} {'Age (days)':<12} {'Status'}")
            print("-" * 80)
            print(f"{sector_name_filter:<30} {'---':<25} {'---':<12} {result['status']}")
            return 0

    print(f"{'Sector':<30} {'Hydrated':<25} {'Age (days)':<12} {'Status'}")
    print("-" * 80)

    if not sectors:
        print("No hydrated sectors found.")
        return 0

    for slug, entry in sorted(sectors.items()):
        sector_name = entry["sector_name"]
        result = check_sector_freshness(sector_name, project_root=root)
        hydrated_at = result.get("hydrated_at", "---")
        age_days = result.get("age_days", "---")
        status = result["status"]
        print(f"{sector_name:<30} {str(hydrated_at):<25} {str(age_days):<12} {status}")

    return 0


def _cmd_build_review_package(
    tickers: list[str],
    out_dir: str,
    structured_analysis_path: str | None,
    focus: str | None,
    research_question: str | None,
    gemini_model: str | None,
    fresh: bool = False,
    use_analyst: bool = False,
) -> int:
    config = load_config()
    from .fmp import _default_transport
    store = FmpCacheStore(_default_fmp_cache_dir())
    fmp_transport = cached_transport(_default_transport, store, fresh=fresh)
    result = build_review_package(
        tickers,
        out_dir=Path(out_dir),
        structured_analysis_path=Path(structured_analysis_path) if structured_analysis_path else None,
        config=config,
        fmp_transport=fmp_transport,
        focus=focus,
        research_question=research_question,
        gemini_model=gemini_model or "gemini-3-pro-preview",
        use_analyst=use_analyst,
    )
    print(
        json.dumps(
            {
                "out_dir": str(result.out_dir),
                "stop_at": result.live_scan_result.stop_at,
                "written_paths": {key: str(path) for key, path in result.written_paths.items()},
            },
            indent=2,
        )
    )
    return 0


def _cmd_review_holding(
    tickers: list[str],
    holdings_path: str,
    json_out: str | None,
) -> int:
    from datetime import date, datetime

    from .schemas import validate_instance

    manifest_path = Path(holdings_path)
    if not manifest_path.exists():
        print(f"Error: holdings manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    manifest = load_json(manifest_path)
    schema = load_json(holdings_schema_path())
    validate_instance(manifest, schema)

    holdings_by_ticker = {h["ticker"]: h for h in manifest["holdings"]}

    missing = [t for t in tickers if t not in holdings_by_ticker]
    if missing:
        print(f"Error: tickers not found in manifest: {', '.join(missing)}", file=sys.stderr)
        return 1

    config = load_config()
    fmp = FmpClient(config.fmp_api_key)

    results = []
    today = date.today()
    for ticker in tickers:
        entry = holdings_by_ticker[ticker]
        quote = fmp.quote(ticker)
        current_price = quote["price"]

        scan_date = datetime.strptime(entry["scan_date"], "%Y-%m-%d").date()
        elapsed_years = (today - scan_date).days / 365.25
        years_remaining = max(entry["base_case_assumptions"]["years"] - elapsed_years, 0.25)

        holding_dict = {
            "ticker": entry["ticker"],
            "purchase_price": entry["purchase_price"],
            "current_weight_pct": entry["current_weight_pct"],
            "base_case_assumptions": entry["base_case_assumptions"],
            "worst_case_assumptions": entry["worst_case_assumptions"],
            "invalidation_triggers": entry["invalidation_triggers"],
            "effective_probability": entry.get("probability_inputs", {}).get("base_probability_pct", 60.0),
            "years_remaining": years_remaining,
        }

        result = review_holding(holding_dict, current_price)
        results.append(result)

    output = results[0] if len(results) == 1 else results
    output_text = json.dumps(output, indent=2)

    if json_out:
        out_path = Path(json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text)

    print(output_text)
    return 0


def _cmd_auto_scan(tickers: list[str], out_dir: str | None, fresh: bool = False) -> int:
    config = load_config()
    config.require("fmp_api_key", "anthropic_api_key")
    from .fmp import _default_transport
    store = FmpCacheStore(_default_fmp_cache_dir())
    transport = cached_transport(_default_transport, store, fresh=fresh)
    result = auto_scan(
        tickers,
        config=config,
        out_dir=Path(out_dir) if out_dir else None,
        fmp_transport=transport,
    )
    summary = result.manifest_path.read_text() if result.manifest_path.exists() else "{}"
    manifest = json.loads(summary)
    s = manifest.get("summary", {})
    print(f"Auto-scan complete: {s.get('total', 0)} tickers scanned")
    print(f"  PASS: {s.get('pass', 0)}  FAIL: {s.get('fail', 0)}  ERROR: {s.get('error', 0)}  PENDING: {s.get('pending_review', 0)}")
    print(f"  Manifest: {result.manifest_path}")
    return 0


def _cmd_sector_scan(
    sector_name: str,
    out_dir: str | None,
    max_workers: int,
    exclude_industry: list[str] | None,
    fresh: bool = False,
) -> int:
    config = load_config()
    config.require("fmp_api_key", "anthropic_api_key", "gemini_api_key")
    from .fmp import _default_transport
    store = FmpCacheStore(_default_fmp_cache_dir())
    transport = cached_transport(_default_transport, store, fresh=fresh)
    fmp_client = FmpClient(config.fmp_api_key, transport=transport)
    result = sector_scan(
        sector_name,
        config=config,
        out_dir=Path(out_dir) if out_dir else None,
        max_workers=max_workers,
        excluded_industries=exclude_industry,
        fmp_transport=transport,
        fmp_client=fmp_client,
    )
    summary = result.manifest_path.read_text() if result.manifest_path.exists() else "{}"
    manifest = json.loads(summary)
    s = manifest.get("summary", {})
    print(f"Sector scan complete: {sector_name}")
    print(f"  Tickers found: {s.get('total', 0)}")
    print(f"  PASS: {s.get('pass', 0)}  FAIL: {s.get('fail', 0)}  ERROR: {s.get('error', 0)}  PENDING: {s.get('pending_review', 0)}")
    print(f"  Manifest: {result.manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate EdenFinTech Python bootstrap assets")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate-assets")
    subparsers.add_parser("run-regression")

    show_contract = subparsers.add_parser("show-contract")
    show_contract.add_argument(
        "stage_id",
        choices=["screening", "cluster_analysis", "epistemic_review", "report_assembly", "codex_final_judge"],
    )

    run_scan = subparsers.add_parser("run-scan")
    run_scan.add_argument("input_path")
    run_scan.add_argument("--json-out")
    run_scan.add_argument("--markdown-out")
    run_scan.add_argument("--execution-log-out")

    validate_scan_input = subparsers.add_parser("validate-scan-input")
    validate_scan_input.add_argument("input_path")

    build_scan_input = subparsers.add_parser("build-scan-input")
    build_scan_input.add_argument("raw_input_path")
    build_scan_input.add_argument("--json-out")

    build_structured_analysis_template = subparsers.add_parser("build-structured-analysis-template")
    build_structured_analysis_template.add_argument("raw_bundle_path")
    build_structured_analysis_template.add_argument("--json-out")

    generate_structured_analysis_draft = subparsers.add_parser("generate-structured-analysis-draft")
    generate_structured_analysis_draft.add_argument("raw_bundle_path")
    generate_structured_analysis_draft.add_argument("--json-out")

    generate_llm_analysis_draft_parser = subparsers.add_parser("generate-llm-analysis-draft")
    generate_llm_analysis_draft_parser.add_argument("raw_bundle_path")
    generate_llm_analysis_draft_parser.add_argument("--json-out")

    review_structured_analysis = subparsers.add_parser("review-structured-analysis")
    review_structured_analysis.add_argument("structured_analysis_path")
    review_structured_analysis.add_argument("--json-out")
    review_structured_analysis.add_argument("--markdown-out")
    review_structured_analysis.add_argument("--overlay-out")
    review_structured_analysis.add_argument(
        "--set-note",
        action="append",
        help="Use FIELD_PATH=NOTE or TICKER:FIELD_PATH=NOTE to update review_note without changing judgments.",
    )

    suggest_review_notes = subparsers.add_parser("suggest-review-notes")
    suggest_review_notes.add_argument("structured_analysis_path")
    suggest_review_notes.add_argument("--json-out")
    suggest_review_notes.add_argument("--markdown-out")

    finalize_structured_analysis = subparsers.add_parser("finalize-structured-analysis")
    finalize_structured_analysis.add_argument("structured_analysis_path")
    finalize_structured_analysis.add_argument("--reviewer", required=True)
    finalize_structured_analysis.add_argument("--json-out")
    finalize_structured_analysis.add_argument(
        "--final-status",
        choices=["HUMAN_CONFIRMED", "HUMAN_EDITED"],
        default="HUMAN_CONFIRMED",
    )
    finalize_structured_analysis.add_argument("--note")

    run_judge = subparsers.add_parser("run-judge")
    run_judge.add_argument("report_path")
    run_judge.add_argument("execution_log_path")

    fetch_fmp_bundle = subparsers.add_parser("fetch-fmp-bundle")
    fetch_fmp_bundle.add_argument("tickers", nargs="+")
    fetch_fmp_bundle.add_argument("--json-out")
    fetch_fmp_bundle.add_argument("--fresh", action="store_true", help="Bypass cache and fetch live data")

    fetch_gemini_bundle = subparsers.add_parser("fetch-gemini-bundle")
    fetch_gemini_bundle.add_argument("tickers", nargs="+")
    fetch_gemini_bundle.add_argument("--json-out")
    fetch_gemini_bundle.add_argument("--focus")
    fetch_gemini_bundle.add_argument("--research-question")
    fetch_gemini_bundle.add_argument("--model")

    merge_raw_bundles = subparsers.add_parser("merge-raw-bundles")
    merge_raw_bundles.add_argument("fmp_bundle_path")
    merge_raw_bundles.add_argument("gemini_bundle_path")
    merge_raw_bundles.add_argument("--json-out")

    run_live_scan = subparsers.add_parser("run-live-scan")
    run_live_scan.add_argument("tickers", nargs="+")
    run_live_scan.add_argument("--out-dir", required=True)
    run_live_scan.add_argument("--stop-at", choices=["raw-bundle", "scan-input", "report"], default="raw-bundle")
    run_live_scan.add_argument("--structured-analysis-path")
    run_live_scan.add_argument("--focus")
    run_live_scan.add_argument("--research-question")
    run_live_scan.add_argument("--gemini-model")
    run_live_scan.add_argument("--fresh", action="store_true", help="Bypass FMP cache")

    build_review_package_parser = subparsers.add_parser("build-review-package")
    build_review_package_parser.add_argument("tickers", nargs="+")
    build_review_package_parser.add_argument("--out-dir", required=True)
    build_review_package_parser.add_argument("--structured-analysis-path")
    build_review_package_parser.add_argument("--focus")
    build_review_package_parser.add_argument("--research-question")
    build_review_package_parser.add_argument("--gemini-model")
    build_review_package_parser.add_argument("--fresh", action="store_true", help="Bypass FMP cache")
    build_review_package_parser.add_argument("--use-analyst", action="store_true", default=False, help="Use Claude analyst agent instead of deterministic machine draft.")

    subparsers.add_parser("cache-status")
    subparsers.add_parser("cache-clear")

    hydrate_sector_p = subparsers.add_parser("hydrate-sector")
    hydrate_sector_p.add_argument("sector_name")
    hydrate_sector_p.add_argument("--sub-sectors", nargs="+", help="Override sub-sector list")
    hydrate_sector_p.add_argument("--model", default=None, help="Gemini model override")

    sector_status_p = subparsers.add_parser("sector-status")
    sector_status_p.add_argument("--sector", default=None, help="Check specific sector")

    auto_scan_p = subparsers.add_parser("auto-scan")
    auto_scan_p.add_argument("tickers", nargs="+")
    auto_scan_p.add_argument("--out-dir", default=None)
    auto_scan_p.add_argument("--fresh", action="store_true", help="Bypass cache")

    sector_scan_p = subparsers.add_parser("sector-scan")
    sector_scan_p.add_argument("sector_name")
    sector_scan_p.add_argument("--out-dir", default=None)
    sector_scan_p.add_argument("--max-workers", type=int, default=3)
    sector_scan_p.add_argument("--exclude-industry", nargs="*", help="Industries to exclude")
    sector_scan_p.add_argument("--fresh", action="store_true", help="Bypass cache")

    review_holding_p = subparsers.add_parser("review-holding")
    review_holding_p.add_argument("tickers", nargs="+")
    review_holding_p.add_argument("--holdings-path", default="data/holdings/holdings.json")
    review_holding_p.add_argument("--json-out", default=None)

    subparsers.add_parser("show-scan-template")
    subparsers.add_parser("show-raw-scan-template")
    subparsers.add_parser("show-scan-schema")
    subparsers.add_parser("show-gemini-schema")
    subparsers.add_parser("show-structured-analysis-schema")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-assets":
        return _cmd_validate_assets()
    if args.command == "run-regression":
        return _cmd_run_regression()
    if args.command == "show-contract":
        return _cmd_show_contract(args.stage_id)
    if args.command == "run-scan":
        return _cmd_run_scan(args.input_path, args.json_out, args.markdown_out, args.execution_log_out)
    if args.command == "show-scan-template":
        return _cmd_show_scan_template()
    if args.command == "validate-scan-input":
        return _cmd_validate_scan_input(args.input_path)
    if args.command == "build-scan-input":
        return _cmd_build_scan_input(args.raw_input_path, args.json_out)
    if args.command == "build-structured-analysis-template":
        return _cmd_build_structured_analysis_template(args.raw_bundle_path, args.json_out)
    if args.command == "generate-structured-analysis-draft":
        return _cmd_generate_structured_analysis_draft(args.raw_bundle_path, args.json_out)
    if args.command == "generate-llm-analysis-draft":
        return _cmd_generate_llm_analysis_draft(args.raw_bundle_path, args.json_out)
    if args.command == "review-structured-analysis":
        return _cmd_review_structured_analysis(
            args.structured_analysis_path,
            args.json_out,
            args.markdown_out,
            args.overlay_out,
            args.set_note,
        )
    if args.command == "suggest-review-notes":
        return _cmd_suggest_review_notes(
            args.structured_analysis_path,
            args.json_out,
            args.markdown_out,
        )
    if args.command == "finalize-structured-analysis":
        return _cmd_finalize_structured_analysis(
            args.structured_analysis_path,
            args.reviewer,
            args.json_out,
            args.final_status,
            args.note,
        )
    if args.command == "show-raw-scan-template":
        return _cmd_show_raw_scan_template()
    if args.command == "run-judge":
        return _cmd_run_judge(args.report_path, args.execution_log_path)
    if args.command == "cache-status":
        return _cmd_cache_status()
    if args.command == "cache-clear":
        return _cmd_cache_clear()
    if args.command == "fetch-fmp-bundle":
        return _cmd_fetch_fmp_bundle(args.tickers, args.json_out, fresh=args.fresh)
    if args.command == "fetch-gemini-bundle":
        return _cmd_fetch_gemini_bundle(
            args.tickers,
            args.json_out,
            args.focus,
            args.research_question,
            args.model,
        )
    if args.command == "merge-raw-bundles":
        return _cmd_merge_raw_bundles(args.fmp_bundle_path, args.gemini_bundle_path, args.json_out)
    if args.command == "run-live-scan":
        return _cmd_run_live_scan(
            args.tickers,
            args.out_dir,
            args.stop_at,
            args.structured_analysis_path,
            args.focus,
            args.research_question,
            args.gemini_model,
            fresh=args.fresh,
        )
    if args.command == "build-review-package":
        return _cmd_build_review_package(
            args.tickers,
            args.out_dir,
            args.structured_analysis_path,
            args.focus,
            args.research_question,
            args.gemini_model,
            fresh=args.fresh,
            use_analyst=args.use_analyst,
        )
    if args.command == "hydrate-sector":
        return _cmd_hydrate_sector(args.sector_name, args.sub_sectors, args.model)
    if args.command == "sector-status":
        return _cmd_sector_status(args.sector)
    if args.command == "auto-scan":
        return _cmd_auto_scan(args.tickers, args.out_dir, fresh=args.fresh)
    if args.command == "sector-scan":
        return _cmd_sector_scan(
            args.sector_name, args.out_dir, args.max_workers,
            args.exclude_industry, fresh=args.fresh,
        )
    if args.command == "review-holding":
        return _cmd_review_holding(args.tickers, args.holdings_path, args.json_out)
    if args.command == "show-scan-schema":
        return _cmd_show_scan_schema()
    if args.command == "show-gemini-schema":
        return _cmd_show_gemini_schema()
    if args.command == "show-structured-analysis-schema":
        return _cmd_show_structured_analysis_schema()

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
