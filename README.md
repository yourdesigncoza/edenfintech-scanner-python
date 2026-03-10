# EdenFinTech Scanner

A deterministic equity scan pipeline that consumes structured research inputs, applies stage contracts, and emits JSON reports with markdown summaries. Built for disciplined, repeatable investment analysis.

## Requirements

- Python 3.11+
- API keys for data retrieval (see [Environment Variables](#environment-variables))

## Quick Start

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in editable mode
pip install -e .

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your API keys

# Validate methodology assets
edenfintech-bootstrap validate-assets
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `FMP_API_KEY` | Yes | Financial Modeling Prep — quantitative data (price, revenue, FCF) |
| `GEMINI_API_KEY` | Yes | Google Gemini — qualitative evidence (catalysts, risks, moat, management) |
| `ANTHROPIC_API_KEY` | For analyst | Claude — LLM-powered analysis drafts |
| `OPENAI_API_KEY` | No | Enables API judge; falls back to deterministic local judge |
| `CODEX_JUDGE_MODEL` | No | Model for judge calls (default: `gpt-5-codex`) |
| `ANALYST_MODEL` | No | Model for analyst drafts (default: `claude-sonnet-4-5-20250514`) |

## Architecture

```
src/edenfintech_scanner_bootstrap/
├── Data Retrieval     fmp.py, gemini.py
├── Structured Analysis  field_generation.py, structured_analysis.py, analyst.py
├── Pipeline Core      pipeline.py, scoring.py, reporting.py
├── Orchestration      live_scan.py, review_package.py, scanner.py, cli.py
├── Holdings           holding_review.py
├── Sectors            sector.py
└── Supporting         importers.py, judge.py, schemas.py, validation.py,
                       regression.py, config.py, cache.py, assets.py
```

### Data Retrieval

**FMP adapter** (`fmp.py`) fetches quantitative bundles — price history, revenue, free cash flow. Results are cached locally (`data/cache/fmp/`) with TTL-based expiration.

**Gemini adapter** (`gemini.py`) fetches qualitative evidence — catalysts, risks, moat assessment, management quality. Supports custom focus areas and research questions.

Both adapters output bundles conforming to schemas in `assets/methodology/`.

### Structured Analysis

Generates machine-draft overlays from merged raw bundles with per-field provenance tracking. The overlay lifecycle:

1. **DRAFT** — auto-generated from raw data
2. **Reviewed** — human adds `review_note` per field
3. **FINALIZED** — promoted only after all fields have explicit review notes

An optional LLM analyst (`analyst.py`) can generate richer drafts using Claude.

### Pipeline Core

Deterministic scan execution through contract-governed stages:

1. **Screening** — 5 checks: solvency, dilution, revenue growth, ROIC, valuation
2. **Cluster analysis** — groups findings by theme
3. **Epistemic review** — assesses confidence and uncertainty
4. **Report assembly** — produces final JSON report + markdown summary

`scoring.py` contains all financial math: CAGR, floor price, decision score, confidence bands.

### Automation

**Auto-scan** (`scanner.py`) runs end-to-end scans for a list of tickers — retrieval, analysis, pipeline, and manifesting results with PASS/FAIL/PENDING status.

**Sector scan** discovers tickers within a sector via hydrated sector knowledge, then batch-scans them with configurable parallelism and industry exclusions.

**Holdings review** (`holding_review.py`) evaluates existing portfolio positions against current market prices, recalculating expected returns and generating action signals.

## Operator Workflow

### Single-ticker scan with human review

```bash
# 1. Build review package (fetches data, generates draft overlay)
edenfintech-bootstrap build-review-package AAPL --out-dir runs/aapl-01

# 2. Review artifacts in runs/aapl-01/review/
#    - review-checklist.md
#    - review-note-suggestions.md
#    Add review_note to each provenance entry

# 3. Finalize the structured analysis
edenfintech-bootstrap finalize-structured-analysis \
  runs/aapl-01/review/structured-analysis.json \
  --reviewer "Your Name" --json-out runs/aapl-01/final/structured-analysis.json

# 4. Re-run with finalized overlay for full report
edenfintech-bootstrap build-review-package AAPL \
  --out-dir runs/aapl-01-final \
  --structured-analysis-path runs/aapl-01/final/structured-analysis.json
```

### Automated batch scan

```bash
# Scan multiple tickers end-to-end
edenfintech-bootstrap auto-scan AAPL MSFT GOOGL --out-dir runs/batch-01

# Scan an entire sector
edenfintech-bootstrap sector-scan "Technology" --out-dir runs/tech-01 --max-workers 3
```

### Holdings review

```bash
# Review current holdings against live prices
edenfintech-bootstrap review-holding AAPL MSFT --holdings-path data/holdings/holdings.json
```

## CLI Reference

### Data Retrieval

| Command | Description |
|---|---|
| `fetch-fmp-bundle TICKER [...]` | Fetch quantitative data from FMP |
| `fetch-gemini-bundle TICKER [...]` | Fetch qualitative data from Gemini |
| `merge-raw-bundles FMP_PATH GEMINI_PATH` | Merge FMP + Gemini bundles |
| `cache-status` | Show FMP cache state |
| `cache-clear` | Clear FMP cache |

### Analysis

| Command | Description |
|---|---|
| `build-structured-analysis-template RAW_BUNDLE` | Generate empty overlay template |
| `generate-structured-analysis-draft RAW_BUNDLE` | Generate machine-draft overlay |
| `generate-llm-analysis-draft RAW_BUNDLE` | Generate LLM-powered draft (requires `ANTHROPIC_API_KEY`) |
| `review-structured-analysis PATH` | Review overlay, set notes via `--set-note` |
| `suggest-review-notes PATH` | Auto-suggest review notes |
| `finalize-structured-analysis PATH --reviewer NAME` | Promote reviewed overlay to FINALIZED |

### Pipeline

| Command | Description |
|---|---|
| `run-scan INPUT_PATH` | Run deterministic scan pipeline |
| `run-live-scan TICKER [...] --out-dir DIR` | Retrieval + pipeline in one step |
| `build-review-package TICKER [...] --out-dir DIR` | Full review workflow package |
| `auto-scan TICKER [...]` | End-to-end automated scan |
| `sector-scan SECTOR_NAME` | Discover + scan all tickers in a sector |
| `run-judge REPORT_PATH LOG_PATH` | Run final judge on scan report |

### Holdings & Sectors

| Command | Description |
|---|---|
| `review-holding TICKER [...]` | Review portfolio holdings against live prices |
| `hydrate-sector SECTOR_NAME` | Build sector knowledge base via Gemini |
| `sector-status` | Show hydration status of all sectors |

### Utilities

| Command | Description |
|---|---|
| `validate-assets` | Validate methodology contracts, schemas, and rules |
| `run-regression` | Run regression suite against fixture snapshots |
| `show-contract STAGE_ID` | Print a stage contract |
| `show-scan-template` | Print scan input template |
| `show-scan-schema` | Print scan input JSON schema |
| `show-gemini-schema` | Print Gemini bundle JSON schema |
| `show-structured-analysis-schema` | Print structured analysis JSON schema |

## Methodology Assets

```
assets/
├── contracts/       Stage contracts defining required inputs/outputs
│   ├── screening.json
│   ├── cluster_analysis.json
│   ├── epistemic_review.json
│   ├── report_assembly.json
│   └── codex_final_judge.json
├── methodology/     Schemas, templates, and strategy rules
│   ├── strategy-rules.md          ← authoritative methodology reference
│   ├── scoring-formulas.md
│   ├── scan-input.schema.json
│   ├── scan-report.schema.json
│   ├── structured-analysis.schema.json
│   ├── gemini-raw-bundle.schema.json
│   └── holdings.schema.json
├── rules/
│   └── canonical-rulebook.json
└── fixtures/regression/           Regression snapshot fixtures
```

**`strategy-rules.md` is the authoritative methodology reference.** If any code or contract disagrees with it, the methodology file wins.

## Testing

```bash
# Run all unit tests
python -m unittest discover -s tests -v

# Validate methodology assets
edenfintech-bootstrap validate-assets

# Run regression suite
edenfintech-bootstrap run-regression
```

## Key Conventions

- JSON is the source of truth; markdown outputs are rendered views only
- Raw bundle fingerprints flow through the entire pipeline for traceability
- No external dependencies beyond stdlib for core pipeline; `requests` for API adapters
- The overlay lifecycle enforces human review before finalization
- When re-running with a finalized overlay, raw bundles are reused (not refetched) to preserve fingerprint continuity
