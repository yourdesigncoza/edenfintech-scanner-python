# Repository Guidelines

## Project Structure & Module Organization
Core Python code lives in `src/edenfintech_scanner_bootstrap/`. `cli.py` exposes the command surface, `pipeline.py` runs the stage orchestration, `reporting.py` renders markdown and execution logs, `judge.py` runs the config-gated Codex/local review step, `scoring.py` holds deterministic valuation and PCS math, `fmp.py` fetches deterministic market/financial raw-bundle fields, `gemini.py` fetches sourced qualitative raw-bundle fields, `structured_analysis.py` defines the structured-analysis overlay contract between retrieval and normalization, `field_generation.py` emits auditable machine-draft overlays with field-level provenance, `live_scan.py` orchestrates the end-to-end live artifact flow, `importers.py` converts raw research bundles into validated scan inputs, `config.py` loads local environment configuration, `validation.py` checks vendored assets, `regression.py` runs fixture-based checks, and `assets.py` centralizes repository paths. Repository data is under `assets/`: `contracts/` for stage definitions, `methodology/` for source-of-truth docs and schemas, `rules/` for the canonical rulebook, and `fixtures/regression/` for regression inputs plus `manifest.json`. Tests live in `tests/`, including raw importer fixtures plus sanitized wire-format adapter fixtures under `tests/fixtures/`.

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
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-gemini-schema
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-structured-analysis-schema
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli fetch-fmp-bundle RAW1 RAW2 --json-out fmp-raw.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli fetch-gemini-bundle RAW1 RAW2 --focus "payments software" --json-out gemini-raw.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli merge-raw-bundles fmp-raw.json gemini-raw.json --json-out merged-raw.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli build-structured-analysis-template merged-raw.json --json-out structured-analysis.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli generate-structured-analysis-draft merged-raw.json --json-out structured-analysis-draft.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli review-structured-analysis structured-analysis-reviewed.json --json-out review-checklist.json --markdown-out review-checklist.md --overlay-out structured-analysis-reviewed-notes.json --set-note screening_inputs.solvency="Reviewer checked solvency against cash generation history."
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli finalize-structured-analysis structured-analysis-reviewed.json --reviewer "Analyst Name" --json-out structured-analysis-finalized.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli build-scan-input raw-input.json --json-out input.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli validate-scan-input input.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-scan input.json --json-out report.json --markdown-out report.md --execution-log-out execution-log.md
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-judge report.json execution-log.md
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-live-scan RAW1 RAW2 --out-dir runs/demo --stop-at raw-bundle
```

`PYTHONPATH=src` is required in a fresh checkout because the package is not installed into the environment by default. Run `validate-assets` after editing anything in `assets/`, `run-regression` before changing contracts or fixtures, `fetch-fmp-bundle` when you touch deterministic retrieval logic, `fetch-gemini-bundle` or `show-gemini-schema` when you touch qualitative retrieval or its raw contract, `show-structured-analysis-schema`, `build-structured-analysis-template`, `generate-structured-analysis-draft`, `review-structured-analysis`, or `finalize-structured-analysis` when you change the retrieval-to-normalization boundary, `merge-raw-bundles` when you change adapter composition for overlapping tickers, `run-live-scan` when you change end-to-end orchestration, `build-scan-input` plus `validate-scan-input` when you touch importer logic or the raw/structured contracts, `run-scan` when you change stage orchestration, reporting, execution-log output, or scoring logic, and `run-judge` when you touch the review boundary. The merged raw bundle is still not sufficient by itself; `screening_inputs`, `analysis_inputs`, and `epistemic_inputs` must exist before `build-scan-input`. The generated structured-analysis template is intentionally non-executable until its `__REQUIRED__` markers are replaced, `completion_status` is set to `FINALIZED`, its `source_bundle` fingerprint still matches the raw bundle it came from, and its required `field_provenance` coverage no longer contains `MACHINE_DRAFT` statuses. The machine-draft overlay is also non-final: it stays in `DRAFT`, includes `generation_metadata`, and marks generated fields via `field_provenance.status=MACHINE_DRAFT`. `review-structured-analysis` is the workflow helper that surfaces required provenance entries and missing `review_note` coverage without changing judgments or finalization state; its optional markdown output is only a rendered artifact from the JSON review report, not an input format. `finalize-structured-analysis` is the narrow review helper that converts reviewed provenance to `HUMAN_CONFIRMED` or `HUMAN_EDITED` and writes a separate finalized overlay with top-level finalization metadata; it does not invent judgments or rewrite field values, and it will only convert a machine-draft provenance entry if that entry already contains an explicit `review_note`. GitHub Actions now mirrors the main local safety checks by running unit tests, `validate-assets`, and `run-regression` on pushes and pull requests.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, explicit type hints, `from __future__ import annotations`, and small focused functions. Use `snake_case` for modules, functions, variables, and fixture keys; use `PascalCase` for dataclasses such as `ValidationReport`. Keep CLI output deterministic and prefer standard-library-only solutions unless a dependency is clearly justified. No formatter or linter is configured here, so match the surrounding code closely.

## Testing Guidelines
Tests use the standard `unittest` framework. Add new tests in `tests/test_*.py`, and keep each test method scoped to one behavior, for example `test_validate_assets_missing_contract` or `test_exception_candidate_routes_to_pending_human_review`. Keep adapter fixtures close to the real FMP and Gemini wire format instead of storing pre-normalized data, and preserve provider nesting/noise in the official-shape fixtures under `tests/fixtures/`. When changing fixture expectations, update both the JSON fixture and `assets/fixtures/regression/manifest.json`. Changes that affect methodology or contracts should leave validation, regression, and pipeline tests passing.

## Commit & Pull Request Guidelines
This repository was initialized locally and does not have project history yet, so commit conventions could not be derived from prior commits. Use short imperative commit subjects, such as `Add contract validation for missing rule IDs`. Pull requests should summarize the asset or code change, list the commands you ran, and note any changed fixtures, contracts, or methodology files. Include sample CLI output when behavior changes.
