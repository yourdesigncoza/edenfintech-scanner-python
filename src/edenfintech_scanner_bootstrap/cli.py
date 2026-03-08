from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assets import contract_path, gemini_raw_bundle_schema_path, load_json, scan_input_schema_path, structured_analysis_schema_path
from .config import load_config
from .fmp import build_fmp_bundle_with_config, write_fmp_bundle
from .gemini import build_gemini_bundle_with_config, merge_fmp_and_gemini_bundles, write_gemini_bundle
from .importers import build_scan_input_file, load_raw_scan_template_text
from .judge import run_judge_file
from .live_scan import run_live_scan
from .pipeline import load_scan_input_template_text, run_scan_file, validate_scan_input_file
from .regression import run_regression_suite
from .structured_analysis import build_structured_analysis_template_file
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


def _cmd_run_judge(report_path: str, execution_log_path: str) -> int:
    load_config()
    result = run_judge_file(Path(report_path), Path(execution_log_path))
    print(json.dumps(result, indent=2))
    return 0


def _cmd_fetch_fmp_bundle(tickers: list[str], json_out: str | None) -> int:
    config = load_config()
    bundle = build_fmp_bundle_with_config(tickers, config=config)
    if json_out:
        write_fmp_bundle(Path(json_out), bundle)
    print(json.dumps(bundle, indent=2))
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
) -> int:
    config = load_config()
    result = run_live_scan(
        tickers,
        out_dir=Path(out_dir),
        stop_at=stop_at,
        structured_analysis_path=Path(structured_analysis_path) if structured_analysis_path else None,
        config=config,
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

    run_judge = subparsers.add_parser("run-judge")
    run_judge.add_argument("report_path")
    run_judge.add_argument("execution_log_path")

    fetch_fmp_bundle = subparsers.add_parser("fetch-fmp-bundle")
    fetch_fmp_bundle.add_argument("tickers", nargs="+")
    fetch_fmp_bundle.add_argument("--json-out")

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
    if args.command == "show-raw-scan-template":
        return _cmd_show_raw_scan_template()
    if args.command == "run-judge":
        return _cmd_run_judge(args.report_path, args.execution_log_path)
    if args.command == "fetch-fmp-bundle":
        return _cmd_fetch_fmp_bundle(args.tickers, args.json_out)
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
        )
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
