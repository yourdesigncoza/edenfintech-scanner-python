# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

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
- `ANTHROPIC_API_KEY` — Anthropic (required for analyst/validator/epistemic reviewer agents)
- `ANALYST_MODEL` — Claude model for analyst agent (default: `claude-haiku-4-5-20251001`)

Config loads via `config.py:load_config()` which auto-discovers `.env` from project root.

## Architecture

### Package layout: `src/edenfintech_scanner_bootstrap/`

The system is a deterministic scan pipeline that consumes structured research inputs, applies stage contracts, and emits JSON reports + markdown summaries. An LLM agent layer (analyst → validator → epistemic reviewer) automates overlay generation and red-team review.

**Data retrieval layer** — `fmp.py`, `gemini.py`, `cache.py`
Adapter modules that fetch raw bundles from FMP (quantitative: price, revenue, FCF) and Gemini (qualitative: catalysts, risks, moat, management). Output conforms to schemas in `assets/methodology/`. `cache.py` provides per-endpoint TTL caching for FMP responses under `data/cache/`.

**LLM agent layer** — `analyst.py`, `validator.py`, `epistemic_reviewer.py`, `automation.py`
`analyst.py` uses Claude constrained decoding to generate LLM_DRAFT overlays. `validator.py` performs deterministic contradiction detection + LLM adversarial red-team questioning (APPROVE/REJECT). `epistemic_reviewer.py` runs a blind epistemic review with allowlist payload filtering to prevent score leakage. `automation.py` orchestrates the full analyst → validator → epistemic reviewer flow with retry logic.

**Structured analysis layer** — `field_generation.py`, `structured_analysis.py`
Generates machine-draft overlays from merged raw bundles with per-field provenance tracking. The overlay lifecycle: MACHINE_DRAFT → LLM_DRAFT → LLM_EDITED/LLM_CONFIRMED → FINALIZED. `finalize-structured-analysis` refuses to promote entries without explicit `review_note`.

**Pipeline core** — `pipeline.py`, `scoring.py`, `reporting.py`
Deterministic scan execution: screening (5 checks: solvency, dilution, revenue_growth, roic, valuation) → cluster analysis → epistemic review → report assembly. `scoring.py` contains all financial math (CAGR, floor price, decision score, confidence bands).

**Scanning orchestrators** — `scanner.py`, `sector.py`
`scanner.py` provides `auto_scan` (single ticker) and `sector_scan` (entire sector) with integrated hardening gates. `sector.py` handles sector knowledge hydration via Gemini grounded search, staleness tracking, and per-sub-sector structured research stored at `data/sectors/`.

**Hardening** — `hardening.py`
Bias detection gates: probability anchoring detection, evidence quality scoring, and 3-agent unanimous CAGR exception panel. Catches common LLM optimism patterns before overlays reach the deterministic pipeline.

**Holdings** — `holding_review.py`
Forward return refresh, thesis integrity checks, sell triggers, replacement gate, and fresh capital weight computation. All financial math delegates to `scoring.py`.

**Orchestration** — `live_scan.py`, `review_package.py`, `cli.py`
`review_package.py` is the main operator entry point — assembles `raw/`, `review/`, `final/` directories with manifest. `live_scan.py` orchestrates retrieval → merge → template/draft generation. `cli.py` is a thin argparse wrapper exposing all commands.

**Supporting** — `importers.py` (raw→scan-input mapping), `judge.py` (OpenAI or local judge), `schemas.py` (JSON Schema validation), `validation.py` (asset integrity), `regression.py` (fixture-based regression), `config.py` (dotenv + AppConfig), `assets.py` (path helpers).

### Methodology assets: `assets/`

- `contracts/` — Stage contracts (screening, cluster_analysis, epistemic_review, report_assembly, codex_final_judge) defining required inputs/outputs per pipeline stage
- `methodology/` — Scan templates, JSON schemas (`scan-input.schema.json`, `scan-report.schema.json`, `structured-analysis.schema.json`, `gemini-raw-bundle.schema.json`, `holdings.schema.json`, `sector-knowledge.schema.json`), `scoring-formulas.md`, and `strategy-rules.md`
- `rules/` — `canonical-rulebook.json` aligned to `strategy-rules.md`

**If a helper or contract ever disagrees with `assets/methodology/strategy-rules.md`, the methodology file wins.**

### Runtime data: `data/` (gitignored)

- `data/cache/` — FMP response cache (per-endpoint TTL, meta-first write for crash safety)
- `data/sectors/` — Hydrated sector knowledge JSON files
- `data/scans/` — Scan output artifacts

### Operator workflow

**Manual flow:**
1. `build-review-package TICKER --out-dir runs/X` → fetches raw bundles, generates draft overlay, writes review artifacts
2. Human reviews `review/review-checklist.md` and `review/review-note-suggestions.md`, adds `review_note` to provenance entries
3. `finalize-structured-analysis` → promotes reviewed overlay
4. `build-review-package TICKER --out-dir runs/X-final --structured-analysis-path ...` → runs full scan with finalized overlay, writes `final/` artifacts
5. When re-running with a finalized overlay from a prior package, raw bundles are reused (not refetched) to preserve fingerprint continuity

**Automated flow:**
1. `auto-scan TICKER` → runs analyst → validator → epistemic reviewer → full pipeline in one shot
2. `sector-scan SUB_SECTOR` → hydrates sector knowledge, screens tickers via FMP, runs auto-scan on each

### Test fixtures

- `tests/fixtures/fmp/`, `tests/fixtures/gemini/` — Sanitized wire-format fixtures including official-shape variants for response-shape drift testing
- `tests/fixtures/raw/` — Merged/ranked candidate bundles for pipeline tests
- `tests/fixtures/generated/` — Generated overlay fixtures
- `tests/fixtures/analyst/`, `tests/fixtures/reviewer/`, `tests/fixtures/validator/`, `tests/fixtures/sector/` — LLM agent response fixtures
- `assets/fixtures/regression/` — Regression snapshot fixtures

## Key Conventions

- Activate `.venv` before running any commands
- JSON is the source of truth; markdown outputs are rendered views only
- Raw bundle fingerprints flow through the entire pipeline for traceability
- Transport injection pattern: all LLM clients and FMP use `Callable[[dict], dict]` transports for testability
- No external dependencies beyond stdlib for core pipeline; `requests` for API adapters
- Python 3.11+
