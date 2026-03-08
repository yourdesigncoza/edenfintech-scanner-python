from __future__ import annotations

import argparse
import json
import sys

from .assets import contract_path, load_json
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

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
