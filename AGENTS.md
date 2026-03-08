# Repository Guidelines

## Project Structure & Module Organization
Core Python code lives in `src/edenfintech_scanner_bootstrap/`. `cli.py` exposes the command surface, `pipeline.py` runs the stage orchestration, `reporting.py` renders markdown and execution logs, `judge.py` runs the config-gated Codex/local review step, `scoring.py` holds deterministic valuation and PCS math, `fmp.py` fetches deterministic market/financial raw-bundle fields, `importers.py` converts raw research bundles into validated scan inputs, `config.py` loads local environment configuration, `validation.py` checks vendored assets, `regression.py` runs fixture-based checks, and `assets.py` centralizes repository paths. Repository data is under `assets/`: `contracts/` for stage definitions, `methodology/` for source-of-truth docs and schemas, `rules/` for the canonical rulebook, and `fixtures/regression/` for regression inputs plus `manifest.json`. Tests live in `tests/`, including raw importer fixtures under `tests/fixtures/`.

## Build, Test, and Development Commands
Use Python 3.11+.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli validate-assets
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-regression
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-contract screening
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-scan-template
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-raw-scan-template
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-scan-schema
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli fetch-fmp-bundle RAW1 RAW2 --json-out fmp-raw.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli build-scan-input raw-input.json --json-out input.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli validate-scan-input input.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-scan input.json --json-out report.json --markdown-out report.md --execution-log-out execution-log.md
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-judge report.json execution-log.md
```

`PYTHONPATH=src` is required in a fresh checkout because the package is not installed into the environment by default. Run `validate-assets` after editing anything in `assets/`, `run-regression` before changing contracts or fixtures, `fetch-fmp-bundle` when you touch deterministic retrieval logic, `build-scan-input` plus `validate-scan-input` when you touch importer logic or the raw/structured contracts, `run-scan` when you change stage orchestration, reporting, execution-log output, or scoring logic, and `run-judge` when you touch the review boundary.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, explicit type hints, `from __future__ import annotations`, and small focused functions. Use `snake_case` for modules, functions, variables, and fixture keys; use `PascalCase` for dataclasses such as `ValidationReport`. Keep CLI output deterministic and prefer standard-library-only solutions unless a dependency is clearly justified. No formatter or linter is configured here, so match the surrounding code closely.

## Testing Guidelines
Tests use the standard `unittest` framework. Add new tests in `tests/test_*.py`, and keep each test method scoped to one behavior, for example `test_validate_assets_missing_contract` or `test_exception_candidate_routes_to_pending_human_review`. When changing fixture expectations, update both the JSON fixture and `assets/fixtures/regression/manifest.json`. Changes that affect methodology or contracts should leave validation, regression, and pipeline tests passing.

## Commit & Pull Request Guidelines
This repository was initialized locally and does not have project history yet, so commit conventions could not be derived from prior commits. Use short imperative commit subjects, such as `Add contract validation for missing rule IDs`. Pull requests should summarize the asset or code change, list the commands you ran, and note any changed fixtures, contracts, or methodology files. Include sample CLI output when behavior changes.
