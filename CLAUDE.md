# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
source .venv/bin/activate   # always activate before working
```

The package is installed in editable mode (`pip install -e .`), so no `PYTHONPATH=src` prefix is needed.

## Build & Test Commands

```bash
# Run all unit tests
python -m unittest discover -s tests -v

# Run a single test file
python -m unittest tests.test_fmp -v

# Run a single test method
python -m unittest tests.test_fmp.TestFmpAdapter.test_quote_parsing -v

# Validate methodology assets (contracts, schemas, rules)
python -m edenfintech_scanner_bootstrap.cli validate-assets

# Run regression suite against fixture snapshots
python -m edenfintech_scanner_bootstrap.cli run-regression
```

CI runs all three (unit tests, asset validation, regression) on every push/PR.

## Environment Variables

Copy `.env.example` to `.env`. Keys used:
- `FMP_API_KEY` — Financial Modeling Prep (required for live retrieval)
- `GEMINI_API_KEY` — Google Gemini (required for qualitative evidence retrieval)
- `OPENAI_API_KEY` — OpenAI (optional; enables API judge, falls back to deterministic local judge)
- `CODEX_JUDGE_MODEL` — model for judge calls (default: `gpt-5-codex`)

Config loads via `config.py:load_config()` which auto-discovers `.env` from project root.

## Architecture

### Package layout: `src/edenfintech_scanner_bootstrap/`

The system is a deterministic scan pipeline that consumes structured research inputs, applies stage contracts, and emits JSON reports + markdown summaries.

**Data retrieval layer** — `fmp.py`, `gemini.py`
Adapter modules that fetch raw bundles from FMP (quantitative: price, revenue, FCF) and Gemini (qualitative: catalysts, risks, moat, management). Output conforms to schemas in `assets/methodology/`.

**Structured analysis layer** — `field_generation.py`, `structured_analysis.py`
Generates machine-draft overlays from merged raw bundles with per-field provenance tracking. The overlay lifecycle: DRAFT → reviewed (with `review_note` per field) → FINALIZED. `finalize-structured-analysis` refuses to promote entries without explicit `review_note`.

**Pipeline core** — `pipeline.py`, `scoring.py`, `reporting.py`
Deterministic scan execution: screening (5 checks: solvency, dilution, revenue_growth, roic, valuation) → cluster analysis → epistemic review → report assembly. `scoring.py` contains all financial math (CAGR, floor price, decision score, confidence bands).

**Orchestration** — `live_scan.py`, `review_package.py`, `cli.py`
`review_package.py` is the main operator entry point — assembles `raw/`, `review/`, `final/` directories with manifest. `live_scan.py` orchestrates retrieval → merge → template/draft generation. `cli.py` is a thin argparse wrapper.

**Supporting** — `importers.py` (raw→scan-input mapping), `judge.py` (OpenAI or local judge), `schemas.py` (JSON Schema validation), `validation.py` (asset integrity), `regression.py` (fixture-based regression), `config.py` (dotenv + AppConfig), `assets.py` (path helpers).

### Methodology assets: `assets/`

- `contracts/` — Stage contracts (screening, cluster_analysis, epistemic_review, report_assembly, codex_final_judge) defining required inputs/outputs per pipeline stage
- `methodology/` — Scan templates, JSON schemas (`scan-input.schema.json`, `scan-report.schema.json`, `structured-analysis.schema.json`, `gemini-raw-bundle.schema.json`), and `strategy-rules.md`
- `rules/` — `canonical-rulebook.json` aligned to `strategy-rules.md`

**If a helper or contract ever disagrees with `assets/methodology/strategy-rules.md`, the methodology file wins.**

### Operator workflow

1. `build-review-package TICKER --out-dir runs/X` → fetches raw bundles, generates draft overlay, writes review artifacts
2. Human reviews `review/review-checklist.md` and `review/review-note-suggestions.md`, adds `review_note` to provenance entries
3. `finalize-structured-analysis` → promotes reviewed overlay
4. `build-review-package TICKER --out-dir runs/X-final --structured-analysis-path ...` → runs full scan with finalized overlay, writes `final/` artifacts
5. When re-running with a finalized overlay from a prior package, raw bundles are reused (not refetched) to preserve fingerprint continuity

### Test fixtures

- `tests/fixtures/fmp/`, `tests/fixtures/gemini/` — Sanitized wire-format fixtures including official-shape variants for response-shape drift testing
- `tests/fixtures/raw/` — Merged/ranked candidate bundles for pipeline tests
- `tests/fixtures/generated/` — Generated overlay fixtures
- `assets/fixtures/regression/` — Regression snapshot fixtures

## Key Conventions

- Activate `.venv` before running any commands
- JSON is the source of truth; markdown outputs are rendered views only
- Raw bundle fingerprints flow through the entire pipeline for traceability
- No external dependencies beyond stdlib for core pipeline; `requests` for API adapters
- Python 3.11+
