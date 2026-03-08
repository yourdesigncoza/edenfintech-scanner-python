from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assets import contract_path, load_json, scan_input_schema_path
from .config import load_config
from .importers import build_scan_input_file, load_raw_scan_template_text
from .pipeline import load_scan_input_template_text, run_scan_file, validate_scan_input_file
from .regression import run_regression_suite
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

    subparsers.add_parser("show-scan-template")
    subparsers.add_parser("show-raw-scan-template")
    subparsers.add_parser("show-scan-schema")
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
    if args.command == "show-raw-scan-template":
        return _cmd_show_raw_scan_template()
    if args.command == "show-scan-schema":
        return _cmd_show_scan_schema()

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
